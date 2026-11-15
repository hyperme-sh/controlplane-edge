"""Exact group allocation operation; media and record scopes grant no access."""
PATH='/api/v1/storage/group-allocations/issue'
SCOPE='storage:group-allocations:issue'


def refusal(method, path, claims):
    if path != PATH:
        return 404
    if method != 'POST':
        return 405
    if type(claims) is not dict:
        return 403
    scopes=claims.get('scope')
    if claims.get('azp') != 'controlplane-api-key' or type(scopes) is not str or SCOPE not in scopes.split():
        return 403
    return None
