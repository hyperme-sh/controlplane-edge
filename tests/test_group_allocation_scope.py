import pytest
from controlplane_edge.group_allocation_scope import PATH,SCOPE,refusal


@pytest.mark.parametrize('claims',[None,[],{}, {'azp':'tenant-session','scope':SCOPE},
    {'azp':'controlplane-api-key','scope':[SCOPE]}, {'azp':'controlplane-api-key','scope':'storage:allocations:issue'},
    {'azp':'controlplane-api-key','scope':'storage:records:write'}, {'azp':'controlplane-api-key','scope':'storage:media:write'}])
def test_no_implicit_group_issuance_authority(claims):
    assert refusal('POST',PATH,claims)==403


def test_exact_operation_and_scope():
    claims={'azp':'controlplane-api-key','scope':SCOPE}
    assert refusal('POST',PATH,claims) is None
    assert refusal('POST',PATH,{**claims,'scope':'other '+SCOPE}) is None
    assert refusal('GET',PATH,claims)==405
    assert refusal('POST',PATH+'/extra',claims)==404
