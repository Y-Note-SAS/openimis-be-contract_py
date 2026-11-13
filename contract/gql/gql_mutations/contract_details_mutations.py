from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError

from core.gql.gql_mutations import DeleteInputType
from core.gql.gql_mutations.base_mutation import BaseMutation, BaseDeleteMutation, \
    BaseHistoryModelCreateMutationMixin, BaseHistoryModelUpdateMutationMixin, \
    BaseHistoryModelDeleteMutationMixin
from .mutations import ContractDetailsFromPHInsureeMutationMixin
from contract.apps import ContractConfig
from contract.gql.gql_mutations import ContractDetailsCreateInputType, ContractDetailsUpdateInputType, \
    ContractDetailsCreateFromInsureeInputType
from contract.models import Contract, ContractDetails, ContractDetailsMutation


class ContractDetailsScopeMixin:
    """
    Contract details are written with the contract update right, on a contract the
    author may see (Contract.get_queryset), for an insuree they may see or one of the
    contract's policy holder. The core mixins only checked the login.
    """

    @classmethod
    def _validate_user_and_right(cls, user):
        if type(user) is AnonymousUser or not user.id:
            raise ValidationError("mutation.authentication_required")
        if not user.has_perms(ContractConfig.gql_mutation_update_contract_perms):
            raise PermissionDenied("unauthorized")

    @classmethod
    def _scoped_contract(cls, user, contract_id):
        contract = Contract.get_queryset(Contract.objects.filter(id=contract_id), user).first() \
            if contract_id else None
        if contract is None:
            raise ValidationError(f"Contract {contract_id} not found")
        return contract

    @classmethod
    def _check_insuree(cls, user, contract, insuree_id):
        from insuree.models import Insuree
        from policyholder.models import PolicyHolderInsuree
        insuree = Insuree.objects.filter(id=insuree_id, validity_to__isnull=True)
        if Insuree.get_queryset(insuree, user).exists():
            return
        # an insuree of the contract's policy holder (seen with the contract)
        if contract.policy_holder_id and PolicyHolderInsuree.objects.filter(
                policy_holder_id=contract.policy_holder_id, insuree_id=insuree_id, is_deleted=False).exists():
            return
        raise ValidationError(f"Insuree {insuree_id} not found")

    @classmethod
    def _scoped_detail(cls, user, detail_id):
        detail = ContractDetails.get_queryset(ContractDetails.objects.filter(id=detail_id), user).first() \
            if detail_id else None
        if detail is None:
            raise ValidationError(f"Contract details {detail_id} not found")
        return detail


class CreateContractDetailsMutation(ContractDetailsScopeMixin, BaseHistoryModelCreateMutationMixin, BaseMutation):
    _mutation_class = "ContractDetailsMutation"
    _mutation_module = "contract"
    _model = ContractDetails

    @classmethod
    def _validate_mutation(cls, user, **data):
        cls._validate_user_and_right(user)
        contract = cls._scoped_contract(user, data.get('contract_id'))
        cls._check_insuree(user, contract, data.get('insuree_id'))
        # the row is created, never designated: an existing id would be overwritten
        if data.get('id') and ContractDetails.objects.filter(id=data['id']).exists():
            raise ValidationError("mutation.code_already_taken")

    @classmethod
    def _mutate(cls, user, **data):
        client_mutation_id = data.get("client_mutation_id")
        if "client_mutation_id" in data:
            data.pop('client_mutation_id')
        if "client_mutation_label" in data:
            data.pop('client_mutation_label')
        contract_detail = cls.create_object(user=user, object_data=data)
        ContractDetailsMutation.object_mutated(user, client_mutation_id=client_mutation_id, contract_detail=contract_detail)
        return None

    class Input(ContractDetailsCreateInputType):
        pass


class UpdateContractDetailsMutation(ContractDetailsScopeMixin, BaseHistoryModelUpdateMutationMixin, BaseMutation):
    _mutation_class = "ContractDetailsMutation"
    _mutation_module = "contract"
    _model = ContractDetails

    @classmethod
    def _validate_mutation(cls, user, **data):
        cls._validate_user_and_right(user)
        detail = cls._scoped_detail(user, data.get('id'))
        contract = detail.contract
        if data.get('contract_id') and str(data['contract_id']) != str(detail.contract_id):
            contract = cls._scoped_contract(user, data['contract_id'])
        if data.get('insuree_id') and (data['insuree_id'] != detail.insuree_id or contract != detail.contract):
            cls._check_insuree(user, contract, data['insuree_id'])

    class Input(ContractDetailsUpdateInputType):
        pass


class DeleteContractDetailsMutation(ContractDetailsScopeMixin, BaseHistoryModelDeleteMutationMixin, BaseDeleteMutation):
    _mutation_class = "ContractDetailsMutation"
    _mutation_module = "contract"
    _model = ContractDetails

    @classmethod
    def _validate_mutation(cls, user, **data):
        # the target is looked up through ContractDetails.get_queryset (target_queryset)
        cls._validate_user_and_right(user)

    class Input(DeleteInputType):
        pass


class CreateContractDetailByPolicyHolderInsureeMutation(ContractDetailsFromPHInsureeMutationMixin, BaseMutation):
    _mutation_class = "CreateContractDetailByPolicyHolderInsureetMutation"
    _mutation_module = "contract"
    _model = ContractDetails

    class Input(ContractDetailsCreateFromInsureeInputType):
        pass
