"""Exact group wrap paths and independent read/write service authority."""
import re
PREFIX='/api/v1/storage/groups/wraps/'
PATTERN=r'/api/v1/storage/groups/wraps/set_p_[a-f0-9]{128}_[a-f0-9]{32}/[a-f0-9]{64}'


def refusal(method,path,claims):
    if type(path) is not str or re.fullmatch(PATTERN,path) is None:return 404
    if method not in ('GET','PUT'):return 405
    if type(claims) is not dict:return 403
    scopes=claims.get('scope')
    required='storage:groups:wraps:'+('read' if method=='GET' else 'write')
    if claims.get('azp')!='controlplane-api-key' or type(scopes) is not str or required not in scopes.split():return 403
    return None
