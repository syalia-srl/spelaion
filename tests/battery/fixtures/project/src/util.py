def greet(name: str) -> str:
    return f"hello, {name}"


def shout(name: str) -> str:
    # TODO: unicode
    return greet(name).upper()
