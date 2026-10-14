class DomainError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def response(self):
        return {"error": {"code": self.code, "message": self.message}}


class Missing(DomainError):
    def __init__(self, resource):
        super().__init__("NOT_FOUND", f"{resource} not found", 404)
