class ParserError(Exception):
    """Base parser exception."""


class UnknownParserType(ParserError):
    pass


class DatabaseLoadError(ParserError):
    pass

class UpdateError(ParserError):
    pass