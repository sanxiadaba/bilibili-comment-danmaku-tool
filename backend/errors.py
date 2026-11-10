"""请求层共用异常。"""

class BadRequestError(ValueError):
    pass


class RequestTooLargeError(ValueError):
    pass
