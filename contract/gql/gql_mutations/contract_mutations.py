from core.gql.gql_mutations import DeleteInputType, mutation_on_uuids_from_filter_business_model
from core.gql.gql_mutations.base_mutation  import BaseMutation, BaseDeleteMutation
from .mutations import ContractCreateMutationMixin, ContractUpdateMutationMixin, \
    ContractDeleteMutationMixin, ContractSubmitMutationMixin, \
    ContractApproveMutationMixin, ContractCounterMutationMixin, \
    ContractAmendMutationMixin, ContractRenewMutationMixin, ContractCreateInvoiceMutationMixin
from contract.models import Contract
from contract.gql.gql_types import ContractGQLType
from contract.gql.gql_mutations.input_types import ContractCreateInputType, ContractUpdateInputType, \
    ContractSubmitInputType, ContractApproveInputType, ContractCounterInputType, \
    ContractApproveBulkInputType, ContractAmendInputType, ContractRenewInputType, \
    ContractCounterBulkInputType, ContractCreateInvoiceBulkInputType
from contract.tasks import approve_contracts, counter_contracts, create_invoice_from_contracts
from contract.exceptions import CeleryWorkerError
from kombu.exceptions import OperationalError


def _bulk_failure(cls, exc):
    return [{'message': "Failed to process {} mutation".format(cls._mutation_class), 'detail': str(exc)}]


def _scoped_contract_ids(user, data):
    """
    The contracts a bulk mutation acts on, within the user's scope: the uuids given or
    those the extended filters selected (from Contract.objects) are narrowed by
    Contract.get_queryset; a contract out of scope is left out.
    """
    if "uuids" in data:
        ids = list(data["uuids"].values_list("id", flat=True)) \
            if hasattr(data["uuids"], "values_list") else list(data["uuids"])
    else:
        ids = list(data.get("contract_uuids") or [])
    if not ids:
        return []
    allowed = {str(contract_id) for contract_id in
               Contract.get_queryset(Contract.objects.filter(id__in=ids), user).values_list("id", flat=True)}
    return [contract_id for contract_id in ids if str(contract_id) in allowed]


class CreateContractMutation(ContractCreateMutationMixin, BaseMutation):
    _mutation_class = "CreateContractMutation"
    _mutation_module = "contract"
    _model = Contract

    class Input(ContractCreateInputType):
        pass


class UpdateContractMutation(ContractUpdateMutationMixin, BaseMutation):
    _mutation_class = "UpdateContractMutation"
    _mutation_module = "contract"
    _model = Contract

    class Input(ContractUpdateInputType):
        pass


class DeleteContractMutation(ContractDeleteMutationMixin, BaseDeleteMutation):
    _mutation_class = "DeleteContractMutation"
    _mutation_module = "contract"
    _model = Contract

    class Input(DeleteInputType):
        pass


class SubmitContractMutation(ContractSubmitMutationMixin, BaseMutation):
    _mutation_class = "SubmitContractMutation"
    _mutation_module = "contract"
    _model = Contract

    class Input(ContractSubmitInputType):
        pass


class ApproveContractMutation(ContractApproveMutationMixin, BaseMutation):
    _mutation_class = "ApproveContractMutation"
    _mutation_module = "contract"
    _model = Contract

    class Input(ContractApproveInputType):
        pass


class ApproveContractBulkMutation(ContractApproveMutationMixin, BaseMutation):
    _mutation_class = "ApproveContractBulkMutation"
    _mutation_module = "contract"
    _model = Contract

    @classmethod
    @mutation_on_uuids_from_filter_business_model(Contract, ContractGQLType, 'extended_filters', {})
    def async_mutate(cls, user, **data):
        # the override skipped BaseMutation.async_mutate, hence the rights check
        try:
            cls._validate_mutation(user, **data)
        except Exception as exc:
            return _bulk_failure(cls, exc)
        error_message = None
        if "client_mutation_id" in data:
            data.pop('client_mutation_id')
        if "client_mutation_label" in data:
            data.pop('client_mutation_label')
        if "contract_uuids" in data or "uuids" in data:
            error_message = cls.approve_contracts(user=user, contracts=data)
        return error_message

    def _check_celery_status(cls):
        try:
            from openIMIS.celery import app as celery_app
            connection = celery_app.broker_connection().ensure_connection(max_retries=3)
            if not connection:
                raise CeleryWorkerError("Celery worker not found. Please, contact your system administrator.")
        except (IOError, OperationalError) as e:
            raise CeleryWorkerError(
                F"Celery connection has failed. Error: {e} \n Please, contact your system administrator.")
    @classmethod
    def approve_contracts(cls, user, contracts):
        return approve_contracts(user_id=f'{user.id}', contracts=_scoped_contract_ids(user, contracts))

    class Input(ContractApproveBulkInputType):
        pass


class CounterContractMutation(ContractCounterMutationMixin, BaseMutation):
    _mutation_class = "CounterContractMutation"
    _mutation_module = "contract"
    _model = Contract

    class Input(ContractCounterInputType):
        pass


class ContractCreateInvoiceBulkMutation(ContractCreateInvoiceMutationMixin, BaseMutation):
    _mutation_class = "ContractCreateInvoiceBulkMutation"
    _mutation_module = "contract"
    _model = Contract

    @classmethod
    @mutation_on_uuids_from_filter_business_model(Contract, ContractGQLType, 'extended_filters', {})
    def async_mutate(cls, user, **data):
        # the override skipped BaseMutation.async_mutate: the invoice right was never checked
        try:
            cls._validate_mutation(user, **data)
        except Exception as exc:
            return _bulk_failure(cls, exc)
        if "client_mutation_id" in data:
            data.pop('client_mutation_id')
        if "client_mutation_label" in data:
            data.pop('client_mutation_label')
        if "contract_uuids" in data or "uuids" in data:
            cls.create_contract_invoice(user=user, contracts=data)
        return None

    @classmethod
    def create_contract_invoice(cls, user, contracts):
        return create_invoice_from_contracts(user_id=f'{user.id}', contracts=_scoped_contract_ids(user, contracts))

    class Input(ContractCreateInvoiceBulkInputType):
        pass


class CounterContractBulkMutation(ContractCounterMutationMixin, BaseMutation):
    _mutation_class = "CounterContractBulkMutation"
    _mutation_module = "contract"
    _model = Contract

    @classmethod
    @mutation_on_uuids_from_filter_business_model(Contract, ContractGQLType, 'extended_filters', {})
    def async_mutate(cls, user, **data):
        # the override skipped BaseMutation.async_mutate, hence the rights check
        try:
            cls._validate_mutation(user, **data)
        except Exception as exc:
            return _bulk_failure(cls, exc)
        if "client_mutation_id" in data:
            data.pop('client_mutation_id')
        if "client_mutation_label" in data:
            data.pop('client_mutation_label')
        if "contract_uuids" in data or "uuids" in data:
            cls.counter_contracts(user=user, contracts=data)
        return None

    @classmethod
    def counter_contracts(cls, user, contracts):
        return counter_contracts(user_id=f'{user.id}', contracts=_scoped_contract_ids(user, contracts))

    class Input(ContractCounterBulkInputType):
        pass


class AmendContractMutation(ContractAmendMutationMixin, BaseMutation):
    _mutation_class = "AmendContractMutation"
    _mutation_module = "contract"
    _model = Contract

    class Input(ContractAmendInputType):
        pass


class RenewContractMutation(ContractRenewMutationMixin, BaseMutation):
    _mutation_class = "RenewContractMutation"
    _mutation_module = "contract"
    _model = Contract

    class Input(ContractRenewInputType):
        pass