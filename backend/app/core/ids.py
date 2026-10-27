import secrets


def new_request_id() -> str:
    return "req_" + secrets.token_hex(8)


def new_call_id() -> str:
    return "call_" + secrets.token_hex(8)
