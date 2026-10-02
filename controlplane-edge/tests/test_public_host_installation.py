from controlplane_edge.public_paths import is_public_path


def test_installation_metadata_is_exact_read_only():
    path = "/api/v1/hypermesh/public/host-installation"
    assert is_public_path(path, "GET")
    assert is_public_path(path + "/", "GET")
    for method in ("POST", "PUT", "DELETE"):
        assert not is_public_path(path, method)
    assert not is_public_path(path + "/private", "GET")
