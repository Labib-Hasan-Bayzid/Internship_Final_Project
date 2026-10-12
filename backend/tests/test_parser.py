from app.services.dependency_parser import changed_dependencies


def test_python_change():
    old = "requests==2.31.0\n"
    new = "requests==2.32.1\n"
    changes = changed_dependencies("python", old, new)
    assert len(changes) == 1
    assert changes[0].package == "requests"
    assert changes[0].old_version == "2.31.0"
    assert changes[0].new_version == "2.32.1"


def test_node_change():
    old = '{"dependencies":{"axios":"^1.7.0"}}'
    new = '{"dependencies":{"axios":"^1.8.0"}}'
    changes = changed_dependencies("node", old, new)
    assert len(changes) == 1
    assert changes[0].package == "axios"
    assert changes[0].old_version == "1.7.0"
    assert changes[0].new_version == "1.8.0"


def test_package_lock_change():
    old = '{"name":"demo","packages":{"":{"dependencies":{"axios":"^1.7.0"}},"node_modules/axios":{"version":"1.7.0"}}}'
    new = '{"name":"demo","packages":{"":{"dependencies":{"axios":"^1.8.0"}},"node_modules/axios":{"version":"1.8.0"}}}'
    changes = changed_dependencies("node", old, new, "package-lock.json")
    assert len(changes) == 1
    assert changes[0].package == "axios"
    assert changes[0].old_version == "1.7.0"
    assert changes[0].new_version == "1.8.0"


def test_poetry_lock_change():
    old = '[[package]]\nname = "httpx"\nversion = "0.27.0"\n'
    new = '[[package]]\nname = "httpx"\nversion = "0.28.1"\n'
    changes = changed_dependencies("python", old, new, "poetry.lock")
    assert len(changes) == 1
    assert changes[0].package == "httpx"
