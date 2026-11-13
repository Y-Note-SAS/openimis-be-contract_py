"""
Security parity of the contract module: rows and writes stay within the contracts the
user may see, i.e. the contracts of the policy holders they may see.

- Contract.get_queryset: the contracts of PolicyHolder.get_queryset (a contract without
  policy holder for the module's global query right only); ContractDetails and
  ContractContributionPlanDetails follow through ParentScope; the GQL types are scoped.
- The service targets (update, submit, approve, counter, amend, renew, delete) and the
  bulk mutations look their contract up within that scope; the bulk mutations check
  their right again (their async_mutate override skipped it).
- Contract details are written with the contract update right on a contract in scope.
- The workflow fields (amounts, approval date, amendment) are not client-settable.
- A policy holder insuree added to a contract belongs to its policy holder.

Fixture: core.test_helpers.create_security_tree -> R1>D1>W1>V1 / R2>D2>W2>V2; a policy
holder in each village with an insuree there and a draft contract; `user_a` holds the
contract rights and is assigned district D1 only; `other` holds no right.

Built without contract.tests.helpers / contribution_plan.tests.helpers (they import a
calculation rule Cameroon's calcrule_contribution_income_percentage does not have).
"""
import datetime
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from contribution_plan.models import ContributionPlanBundle
from core.models.openimis_graphql_test_case import openIMISGraphQLTestCase
from core.test_helpers import (
    create_security_tree, create_right_only_user, create_test_interactive_user, get_test_token, perm_ids,
)
from insuree.test_helpers import create_test_insuree
from policyholder.models import PolicyHolder, PolicyHolderInsuree

from contract.apps import ContractConfig as cfg
from contract.models import Contract, ContractDetails, ContractContributionPlanDetails
from contract.services import Contract as ContractService, ContractDetails as ContractDetailsService


def _u(*lists):
    return list(dict.fromkeys(r for lst in lists for r in lst))


CONTRACT_RIGHTS = _u(*[perm_ids(getattr(cfg, name)) for name in (
    "gql_query_contract_perms", "gql_mutation_create_contract_perms", "gql_mutation_update_contract_perms",
    "gql_mutation_delete_contract_perms", "gql_mutation_renew_contract_perms", "gql_mutation_submit_contract_perms",
    "gql_mutation_approve_ask_for_change_contract_perms", "gql_mutation_amend_contract_perms",
    "gql_invoice_create_perms",
)])


def _build(cls, prefix):
    cls.t = create_security_tree(prefix)
    cls.saver = create_test_interactive_user(username=f"{prefix}saver")
    cls.bundle = ContributionPlanBundle(code=f"{prefix}CPB", name=f"{prefix} bundle")
    cls.bundle.save(user=cls.saver)
    for key, village in (("a", cls.t.v1), ("b", cls.t.v2)):
        ph = PolicyHolder(code=f"{prefix}PH{key}", trade_name=f"{prefix} trade {key}", locations=village,
                          date_valid_from=datetime.datetime(2020, 1, 1))
        ph.save(user=cls.saver)
        insuree = create_test_insuree(
            with_family=True, is_head=True,
            custom_props={"chf_id": f"{prefix}0000{1 if key == 'a' else 2}", "current_village": village},
            family_custom_props={"location": village})
        phi = PolicyHolderInsuree(policy_holder=ph, insuree=insuree, contribution_plan_bundle=cls.bundle,
                                  json_ext={}, date_valid_from=datetime.datetime(2020, 1, 1))
        phi.save(user=cls.saver)
        contract = Contract(code=f"{prefix}C{key}", policy_holder=ph, state=Contract.STATE_DRAFT,
                            date_valid_from=datetime.datetime(2020, 1, 1))
        contract.save(user=cls.saver)
        detail = ContractDetails(contract=contract, insuree=insuree, contribution_plan_bundle=cls.bundle)
        detail.save(user=cls.saver)
        setattr(cls, f"ph_{key}", ph)
        setattr(cls, f"ins_{key}", insuree)
        setattr(cls, f"phi_{key}", phi)
        setattr(cls, f"c_{key}", contract)
        setattr(cls, f"cd_{key}", detail)
    cls.user_a = create_right_only_user(f"{prefix.lower()}usera", CONTRACT_RIGHTS, [cls.t.d1.id])
    cls.other = create_right_only_user(f"{prefix.lower()}other", [])


def _ids(queryset):
    return set(queryset.values_list("id", flat=True))


@override_settings(ROW_SECURITY=True)
class ContractReadScopeTest(openIMISGraphQLTestCase):

    @classmethod
    def setUpTestData(cls):
        _build(cls, "CTR")

    def setUp(self):
        cache.clear()

    def _q(self, query, user):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {get_test_token(user)}"}
        content = json.loads(self.query(query, headers=headers).content)
        self.assertNotIn("errors", content, content.get("errors"))
        return content["data"]

    def test_contracts_follow_the_policy_holder(self):
        ids = _ids(Contract.get_queryset(Contract.objects.all(), self.user_a))
        self.assertIn(self.c_a.id, ids)
        self.assertNotIn(self.c_b.id, ids)

    def test_contract_details_follow_the_contract(self):
        ids = _ids(ContractDetails.get_queryset(
            ContractDetails.objects.filter(id__in=[self.cd_a.id, self.cd_b.id]), self.user_a))
        self.assertEqual({self.cd_a.id}, ids)

    def test_contribution_plan_details_follow_the_contract_details(self):
        scope = ContractContributionPlanDetails.row_scope
        self.assertIsNotNone(scope)
        self.assertEqual("contract_details", scope.field)
        sql = str(ContractContributionPlanDetails.get_queryset(
            ContractContributionPlanDetails.objects.all(), self.user_a).query)
        self.assertIn("tblContract", sql.replace('"', ''))

    def test_contract_listed_within_scope(self):
        data = self._q('{ contract { edges { node { code } } } }', self.user_a)
        codes = {e["node"]["code"] for e in data["contract"]["edges"]}
        self.assertIn("CTRCa", codes)
        self.assertNotIn("CTRCb", codes)

    def test_contract_details_listed_within_scope(self):
        data = self._q('{ contractDetails { edges { node { contract { code } } } } }', self.user_a)
        codes = {e["node"]["contract"]["code"] for e in data["contractDetails"]["edges"]}
        self.assertIn("CTRCa", codes)
        self.assertNotIn("CTRCb", codes)

    def test_anonymous_sees_no_contract(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(Contract.get_queryset(Contract.objects.all(), AnonymousUser()).exists())


@override_settings(ROW_SECURITY=True)
class ContractWriteScopeTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        _build(cls, "CTW")

    def setUp(self):
        cache.clear()

    # -- contract details mutations (core mixins checked the login only) ----------------

    def _create_detail(self, user, contract, insuree):
        from contract.gql.gql_mutations.contract_details_mutations import CreateContractDetailsMutation
        before = ContractDetails.objects.count()
        CreateContractDetailsMutation.async_mutate(
            user, contract_id=contract.id, insuree_id=insuree.id, contribution_plan_bundle_id=self.bundle.id)
        return ContractDetails.objects.count() - before

    def test_create_contract_details_needs_the_update_right(self):
        self.assertEqual(0, self._create_detail(self.other, self.c_a, self.ins_a))

    def test_create_contract_details_on_a_contract_out_of_scope(self):
        self.assertEqual(0, self._create_detail(self.user_a, self.c_b, self.ins_b))

    def test_create_contract_details_within_scope(self):
        self.assertEqual(1, self._create_detail(self.user_a, self.c_a, self.ins_a))

    def test_update_contract_details_out_of_scope(self):
        from contract.gql.gql_mutations.contract_details_mutations import UpdateContractDetailsMutation
        UpdateContractDetailsMutation.async_mutate(self.user_a, id=self.cd_b.id, json_param={"hacked": True})
        self.assertNotEqual({"hacked": True}, ContractDetails.objects.get(id=self.cd_b.id).json_param)
        UpdateContractDetailsMutation.async_mutate(self.other, id=self.cd_a.id, json_param={"hacked": True})
        self.assertNotEqual({"hacked": True}, ContractDetails.objects.get(id=self.cd_a.id).json_param)

    def test_delete_contract_details_out_of_scope_or_without_right(self):
        from contract.gql.gql_mutations.contract_details_mutations import DeleteContractDetailsMutation
        DeleteContractDetailsMutation.async_mutate(self.user_a, uuids=[self.cd_b.id])
        self.assertFalse(ContractDetails.objects.get(id=self.cd_b.id).is_deleted)
        DeleteContractDetailsMutation.async_mutate(self.other, uuids=[self.cd_a.id])
        self.assertFalse(ContractDetails.objects.get(id=self.cd_a.id).is_deleted)

    # -- bulk mutations (async_mutate overrides skipped _validate_mutation) -------------

    def test_approve_bulk_checks_the_right_and_the_scope(self):
        from contract.gql.gql_mutations.contract_mutations import ApproveContractBulkMutation
        with mock.patch("contract.gql.gql_mutations.contract_mutations.approve_contracts") as task:
            ApproveContractBulkMutation.async_mutate(self.other, contract_uuids=[self.c_a.id])
            self.assertFalse(task.called)
            ApproveContractBulkMutation.async_mutate(self.user_a, contract_uuids=[self.c_a.id, self.c_b.id])
            self.assertEqual([str(self.c_a.id)], [str(i) for i in task.call_args.kwargs["contracts"]])

    def test_counter_bulk_checks_the_right_and_the_scope(self):
        from contract.gql.gql_mutations.contract_mutations import CounterContractBulkMutation
        with mock.patch("contract.gql.gql_mutations.contract_mutations.counter_contracts") as task:
            CounterContractBulkMutation.async_mutate(self.other, contract_uuids=[self.c_a.id])
            self.assertFalse(task.called)
            CounterContractBulkMutation.async_mutate(self.user_a, contract_uuids=[self.c_b.id])
            self.assertEqual([], list(task.call_args.kwargs["contracts"]))

    def test_invoice_bulk_checks_the_invoice_right_and_the_scope(self):
        from contract.gql.gql_mutations.contract_mutations import ContractCreateInvoiceBulkMutation
        with mock.patch("contract.gql.gql_mutations.contract_mutations.create_invoice_from_contracts") as task:
            ContractCreateInvoiceBulkMutation.async_mutate(self.other, contract_uuids=[self.c_a.id])
            self.assertFalse(task.called)
            ContractCreateInvoiceBulkMutation.async_mutate(self.user_a, contract_uuids=[self.c_a.id, self.c_b.id])
            self.assertEqual([str(self.c_a.id)], [str(i) for i in task.call_args.kwargs["contracts"]])

    def test_invoice_task_invoices_contracts_in_scope_only(self):
        from contract.tasks import create_invoice_from_contracts
        with mock.patch("contract.tasks.ContractToInvoiceService") as service:
            create_invoice_from_contracts(user_id=self.user_a.id, contracts=[self.c_b.id])
            self.assertFalse(service.return_value.create_invoice.called)

    # -- service targets -----------------------------------------------------------------

    def test_service_update_out_of_scope(self):
        output = ContractService(user=self.user_a).update(
            contract={"id": self.c_b.id, "payment_reference": "hacked"})
        self.assertFalse(output and output.get("success"))
        self.assertNotEqual("hacked", Contract.objects.get(id=self.c_b.id).payment_reference)

    def test_service_delete_out_of_scope(self):
        output = ContractService(user=self.user_a).delete(contract={"id": self.c_b.id})
        self.assertFalse(output["success"])
        self.assertFalse(Contract.objects.get(id=self.c_b.id).is_deleted)

    def test_service_submit_out_of_scope(self):
        output = ContractService(user=self.user_a).submit(contract={"id": self.c_b.id})
        self.assertFalse(output["success"])
        self.assertIn("not found", output["detail"])

    def test_service_renew_amend_approve_counter_out_of_scope(self):
        service = ContractService(user=self.user_a)
        for method in ("renew", "amend", "approve", "counter"):
            output = getattr(service, method)(contract={"id": self.c_b.id})
            self.assertFalse(output["success"], method)
            self.assertIn("not found", output["detail"], method)

    # -- mass assignment -----------------------------------------------------------------

    def test_update_ignores_workflow_fields(self):
        output = ContractService(user=self.user_a).update(contract={
            "id": self.c_a.id, "payment_reference": "ref-a", "amount_due": 999, "amount_notified": 999,
            "amount_rectified": 999, "amendment": 7, "date_approved": datetime.datetime(2021, 1, 1),
        })
        self.assertTrue(output["success"], output)
        contract = Contract.objects.get(id=self.c_a.id)
        self.assertEqual("ref-a", contract.payment_reference)
        self.assertNotEqual(999, contract.amount_due)
        self.assertNotEqual(999, contract.amount_rectified)
        self.assertNotEqual(7, contract.amendment)
        self.assertIsNone(contract.date_approved)

    def test_create_ignores_workflow_fields(self):
        output = ContractService(user=self.user_a).create(contract={
            "code": "CTWnew", "amount_due": 999, "amount_rectified": 999, "amendment": 7,
            "date_approved": datetime.datetime(2021, 1, 1),
        })
        self.assertTrue(output["success"], output)
        contract = Contract.objects.get(code="CTWnew")
        self.assertNotEqual(999, contract.amount_due)
        self.assertNotEqual(7, contract.amendment)
        self.assertIsNone(contract.date_approved)

    def test_create_with_a_policy_holder_out_of_scope(self):
        output = ContractService(user=self.user_a).create(contract={"code": "CTWphb", "policy_holder_id": self.ph_b.id})
        self.assertFalse(output["success"])
        self.assertFalse(Contract.objects.filter(code="CTWphb").exists())

    def test_update_with_a_policy_holder_out_of_scope(self):
        floating = Contract(code="CTWfloat", state=Contract.STATE_DRAFT, date_valid_from=datetime.datetime(2020, 1, 1))
        floating.save(user=self.saver)
        output = ContractService(user=self.user_a).update(contract={"id": floating.id, "policy_holder_id": self.ph_b.id})
        self.assertFalse(output["success"])
        self.assertIsNone(Contract.objects.get(id=floating.id).policy_holder_id)

    # -- policy holder insuree -> contract details ---------------------------------------

    def test_ph_insuree_of_another_policy_holder(self):
        before = ContractDetails.objects.filter(contract=self.c_a).count()
        output = ContractDetailsService(user=self.user_a).ph_insuree_to_contract_details(
            contract={"id": self.c_a.id}, ph_insuree={"id": self.phi_b.id})
        self.assertFalse(output["success"])
        self.assertEqual(before, ContractDetails.objects.filter(contract=self.c_a).count())

    def test_ph_insuree_on_a_contract_out_of_scope(self):
        before = ContractDetails.objects.filter(contract=self.c_b).count()
        output = ContractDetailsService(user=self.user_a).ph_insuree_to_contract_details(
            contract={"id": self.c_b.id}, ph_insuree={"id": self.phi_b.id})
        self.assertFalse(output["success"])
        self.assertEqual(before, ContractDetails.objects.filter(contract=self.c_b).count())

    def test_ph_insuree_of_the_contract_policy_holder(self):
        output = ContractDetailsService(user=self.user_a).ph_insuree_to_contract_details(
            contract={"id": self.c_a.id}, ph_insuree={"id": self.phi_a.id})
        self.assertTrue(output["success"], output)
