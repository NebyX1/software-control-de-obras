class ApiError(Exception):
    def __init__(self, code, message, status=400, fields=None, extra=None):
        super().__init__(message)
        self.code, self.message, self.status, self.fields = code, message, status, fields or {}
        self.extra = extra or {}


def require(condition, code, message, status=400, fields=None, extra=None):
    if not condition:
        raise ApiError(code, message, status, fields, extra)


def conflict(code, message, extra=None):
    return ApiError(code, message, 409, extra=extra)
