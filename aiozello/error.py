#
# Client Errors
#


class TokenGenerationError(Exception):
    """Error during token generation."""


#
# Server Errors
#


class UnknownCommandError(Exception):
    """Server didn't recognize the command received from the client."""

    pass


class InternalServerError(Exception):
    """An internal error occurred within the server. If the error persists please contact us at support@zello.com"""

    pass


class InvalidJsonError(Exception):
    """The command received included malformed JSON."""

    pass


class InvalidRequestError(Exception):
    """The server couldn't recognize command format."""

    pass


class NotAuthorizedError(Exception):
    """Username, password or token are not valid."""

    pass


class NotLoggedInError(Exception):
    """Server received a command before successful `logon`."""

    pass


class NotEnoughParamsError(Exception):
    """The command doesn't include some of the required attributes."""

    pass


class ServerClosedConnectionError(Exception):
    """The connection to Zello network was closed. You can try re-connecting."""

    pass


class ChannelIsNotReadyError(Exception):
    """Channel you are trying to talk to is not yet connected. Wait for channel `online` status before sending a message."""

    pass


class ListenOnlyConnectionError(Exception):
    """The client tried to send a message over listen-only connection."""

    pass


class FailedToStartStreamError(Exception):
    """Unable to start the stream for unknown reason. You can try again later."""

    pass


class FailedToStopStreamError(Exception):
    """Unable to stop the stream for unknown reason. This error is safe to ignore."""

    pass


class FailedToSendDataError(Exception):
    """An error occurred while trying to send stream data packet."""

    pass


class InvalidAudioPacketError(Exception):
    """Malformed audio packet is received."""

    pass


# From https://github.com/zelloptt/zello-channel-api/blob/master/API.md#error-codes
server_error_mapping = {
    "unknown command": UnknownCommandError,
    "internal server error": InternalServerError,
    "invalid json": InvalidJsonError,
    "invalid request": InvalidRequestError,
    "not authorized": NotAuthorizedError,
    "not logged in": NotLoggedInError,
    "not enough params": NotEnoughParamsError,
    "server closed connection": ServerClosedConnectionError,
    "channel is not ready": ChannelIsNotReadyError,
    "listen only connection": ListenOnlyConnectionError,
    "failed to start stream": FailedToStartStreamError,
    "failed to stop stream": FailedToStopStreamError,
    "failed to send data": FailedToSendDataError,
    "invalid audio packet": InvalidAudioPacketError,
}


def get_exception_by_error_code(error_code):
    try:
        return server_error_mapping.get(error_code)
    except KeyError:
        raise ValueError(f"Unknown server error code: {error_code}")
