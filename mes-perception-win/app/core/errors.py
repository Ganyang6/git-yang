class AppError(Exception):
    """Structured application error with HTTP mapping.

    Attributes:
      message: human-readable error message
      code: business error code
      http_status_code: HTTP status code to be returned
    """

    def __init__(self, message: str, code: int = 400, http_status_code: int = 400):
        self.message = message
        self.code = code
        self.http_status_code = http_status_code
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "data": None,
        }

    def __str__(self) -> str:
        return f"AppError(code={self.code}, http_status={self.http_status_code}, message={self.message})"
