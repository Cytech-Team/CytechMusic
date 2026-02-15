class CytechlinkException(Exception):
    """Base of all Cytechlink exceptions."""


class NodeException(Exception):
    """Base exception for nodes."""


class NodeCreationError(NodeException):
    """There was a problem while creating the node."""


class NodeConnectionFailure(NodeException):
    """There was a problem while connecting to the node."""


class NodeConnectionClosed(NodeException):
    """The node's connection is closed."""
    pass


class NodeNotAvailable(CytechlinkException):
    """The node is currently unavailable."""
    pass


class NoNodesAvailable(CytechlinkException):
    """There are no nodes currently available."""
    pass


class TrackInvalidPosition(CytechlinkException):
    """An invalid position was chosen for a track."""
    pass


class TrackLoadError(CytechlinkException):
    """There was an error while loading a track."""
    pass


class FilterInvalidArgument(CytechlinkException):
    """An invalid argument was passed to a filter."""
    pass

class FilterTagAlreadyInUse(CytechlinkException):
    """A filter with a tag is already in use by another filter"""
    pass

class FilterTagInvalid(CytechlinkException):
    """An invalid tag was passed or Cytechlink was unable to find a filter tag"""
    pass

class SpotifyAlbumLoadFailed(CytechlinkException):
    """The Cytechlink Spotify client was unable to load an album."""
    pass


class SpotifyTrackLoadFailed(CytechlinkException):
    """The Cytechlink Spotify client was unable to load a track."""
    pass


class SpotifyPlaylistLoadFailed(CytechlinkException):
    """The Cytechlink Spotify client was unable to load a playlist."""
    pass


class InvalidSpotifyClientAuthorization(CytechlinkException):
    """No Spotify client authorization was provided for track searching."""
    pass


class QueueFull(CytechlinkException):
    pass

class OutofList(CytechlinkException):
    pass

class DuplicateTrack(CytechlinkException):
    pass