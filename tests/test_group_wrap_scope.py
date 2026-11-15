import pytest
from controlplane_edge.group_wrap_scope import refusal
PATH='/api/v1/storage/groups/wraps/set_p_'+'a'*128+'_'+'b'*32+'/'+'c'*64


@pytest.mark.parametrize('method,operation',[('GET','read'),('PUT','write')])
def test_separate_scope_and_canonical_path(method,operation):
    scope='storage:groups:wraps:'+operation
    assert refusal(method,PATH,{'azp':'controlplane-api-key','scope':scope}) is None
    for claims in [None,[],{}, {'azp':'other','scope':scope}, {'azp':'controlplane-api-key','scope':[scope]},
                   {'azp':'controlplane-api-key','scope':'storage:media:payload:'+operation}]:
        assert refusal(method,PATH,claims)==403
    for path in [None,PATH+'/extra',PATH.replace('set_p_','media_p_')]:assert refusal(method,path,{})==404
    assert refusal('DELETE',PATH,{})==405
