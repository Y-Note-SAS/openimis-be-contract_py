import graphene
import graphene_django_optimizer as gql_optimizer

from django.db.models import Q
from .services import check_unique_code
from core.gql_queries import ValidationMessageGQLType
from core.schema import signal_mutation_module_before_mutating, OrderedDjangoFilterConnectionField
from core.gql import legacy_row_filters
from core import datetime
from core.models import Validity
from contract.models import Contract, ContractDetails, \
    ContractContributionPlanDetails, ContractMutation
from contract.gql.gql_types import ContractGQLType, ContractDetailsGQLType, \
    ContractContributionPlanDetailsGQLType

from contract.gql.gql_mutations.contract_mutations import CreateContractMutation, \
    UpdateContractMutation, DeleteContractMutation, SubmitContractMutation, ApproveContractMutation, \
    ApproveContractBulkMutation, CounterContractMutation, \
    AmendContractMutation, RenewContractMutation, CounterContractBulkMutation, ContractCreateInvoiceBulkMutation
from contract.gql.gql_mutations.contract_details_mutations import CreateContractDetailsMutation, \
    UpdateContractDetailsMutation, DeleteContractDetailsMutation, \
    CreateContractDetailByPolicyHolderInsureeMutation
from contract.apps import ContractConfig
from contract.utils import filter_amount_contract


class Query(graphene.ObjectType):

    contract = OrderedDjangoFilterConnectionField(
        ContractGQLType,
        client_mutation_id=graphene.String(),
        insuree=graphene.UUID(),
        orderBy=graphene.List(of_type=graphene.String),
        dateValidFrom__Gte=graphene.DateTime(),
        dateValidTo__Lte=graphene.DateTime(),
        amount_from=graphene.Decimal(),
        amount_to=graphene.Decimal(),
        applyDefaultValidityFilter=graphene.Boolean()
    )

    contract_details = OrderedDjangoFilterConnectionField(
        ContractDetailsGQLType,
        client_mutation_id=graphene.String(),
        orderBy=graphene.List(of_type=graphene.String),
    )

    contract_contribution_plan_details = OrderedDjangoFilterConnectionField(
        ContractContributionPlanDetailsGQLType,
        insuree=graphene.UUID(),
        contributionPlanBundle=graphene.UUID(),
        orderBy=graphene.List(of_type=graphene.String),
    )

    validate_contract_code = graphene.Field(
        ValidationMessageGQLType,
        contract_code=graphene.String(required=True),
        description="Check that the specified contract code is unique."
    )

    def resolve_validate_contract_code(self, info, **kwargs):
        if not info.context.user.has_perms(ContractConfig.gql_query_contract_perms):
            if not info.context.user.has_perms(ContractConfig.gql_query_contract_policyholder_portal_perms):
                raise PermissionError("Unauthorized")
        errors = check_unique_code(code=kwargs['contract_code'])
        if errors:
            return ValidationMessageGQLType(False)
        else:
            return ValidationMessageGQLType(True)

    def resolve_contract(self, info, **kwargs):
        if not info.context.user.has_perms(ContractConfig.gql_query_contract_perms):
            if not info.context.user.has_perms(ContractConfig.gql_query_contract_policyholder_portal_perms):
                raise PermissionError("Unauthorized")

        # rows narrowed to the policy holders in scope by Contract.get_queryset
        # (ContractGQLType), which also applies the validity (OP-2029)
        filters = []
        _legacy_validity(info, kwargs)
        client_mutation_id = kwargs.get("client_mutation_id", None)
        if client_mutation_id:
            filters.append(Q(mutations__mutation__client_mutation_id=client_mutation_id))

        insuree = kwargs.get('insuree', None)
        if insuree:
            filters.append(Q(contractdetails__insuree__uuid=insuree))

        # amount filters
        amount_from = kwargs.get('amount_from', None)
        amount_to = kwargs.get('amount_to', None)
        if amount_from or amount_to:
            filters.append(filter_amount_contract(**kwargs))
        return gql_optimizer.query(Contract.objects.filter(*filters).all(), info)

    def resolve_contract_details(self, info, **kwargs):
        if not info.context.user.has_perms(ContractConfig.gql_query_contract_perms):
            if not info.context.user.has_perms(ContractConfig.gql_query_contract_policyholder_portal_perms):
                raise PermissionError("Unauthorized")

        filters = []
        client_mutation_id = kwargs.get("client_mutation_id", None)
        if client_mutation_id:
            filters.append(Q(mutations__mutation__client_mutation_id=client_mutation_id))

        return gql_optimizer.query(ContractDetails.objects.filter(*filters).all(), info)

    def resolve_contract_contribution_plan_details(self, info, **kwargs):
        if not info.context.user.has_perms(ContractConfig.gql_query_contract_perms):
            if not info.context.user.has_perms(ContractConfig.gql_query_contract_policyholder_portal_perms):
                raise PermissionError("Unauthorized")

        query = ContractContributionPlanDetails.objects.all()

        insuree = kwargs.get('insuree', None)
        contribution_plan_bundle = kwargs.get('contributionPlanBundle', None)

        if insuree:
            query = query.filter(
                contract_details__insuree__uuid=insuree
            )

        if contribution_plan_bundle:
            query = query.filter(
                contract_details__contribution_plan_bundle__id=contribution_plan_bundle
            )

        return gql_optimizer.query(query.all(), info)


def _legacy_validity(info, kwargs):
    """
    The validity is applied by Contract.get_queryset (OP-2029); the legacy arguments
    keep their meaning: dateValidFrom__Gte / dateValidTo__Lte a business validity range,
    applyDefaultValidityFilter the rows not yet expired (future-dated ones included,
    as append_validity_filter had it), nothing at all every row.
    """
    if kwargs.get('dateValidFrom__Gte') or kwargs.get('dateValidTo__Lte'):
        return legacy_row_filters(info, kwargs)
    validity = Validity.between(datetime.datetime.now(), None) \
        if kwargs.get('applyDefaultValidityFilter') else Validity.ALL
    return legacy_row_filters(info, kwargs, validity=validity)


class Mutation(graphene.ObjectType):
    create_contract = CreateContractMutation.Field()
    update_contract = UpdateContractMutation.Field()
    delete_contract = DeleteContractMutation.Field()
    submit_contract = SubmitContractMutation.Field()
    approve_contract = ApproveContractMutation.Field()
    approve_bulk_contract = ApproveContractBulkMutation.Field()
    counter_contract = CounterContractMutation.Field()
    counter_bulk_contract = CounterContractBulkMutation.Field()
    amend_contract = AmendContractMutation.Field()
    renew_contract = RenewContractMutation.Field()
    create_contract_invoice_bulk = ContractCreateInvoiceBulkMutation.Field()

    create_contract_details = CreateContractDetailsMutation.Field()
    update_contract_details = UpdateContractDetailsMutation.Field()
    delete_contract_details = DeleteContractDetailsMutation.Field()
    create_contract_details_by_ph_insuree = CreateContractDetailByPolicyHolderInsureeMutation.Field()


def on_contract_mutation(sender, **kwargs):
    uuids = kwargs['data'].get('uuids', [])
    if not uuids:
        uuid = kwargs['data'].get('uuid', None)
        uuids = [uuid] if uuid else []
    if not uuids:
        return []
    # only the contracts the user may see get the mutation linked
    impacted_contracts = Contract.get_queryset(Contract.objects.filter(id__in=uuids), kwargs.get('user'))
    for contract in impacted_contracts:
        ContractMutation.objects.update_or_create(contract=contract, mutation_id=kwargs['mutation_log_id'])
    return []


signal_mutation_module_before_mutating["contract"].connect(on_contract_mutation)
