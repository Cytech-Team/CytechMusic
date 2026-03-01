from enum import Enum, auto


class LoopType(Enum):
    """The enum for the different loop types for Cytechlink

    LoopType.off: 1
    LoopType.track: 2
    LoopType.queue: 3

    """

    off = auto()
    track = auto()
    queue = auto()


class SearchType(Enum):
    """The enum for the different search types for Cytechlink.
    This feature is exclusively for the Spotify search feature of Cytechlink.
    If you are not using this feature, this class is not necessary.

    SearchType.ytsearch searches using regular Youtube,
    which is best for all scenarios.

    SearchType.ytmsearch searches using YouTube Music,
    which is best for getting audio-only results.

    SearchType.scsearch searches using SoundCloud,
    which is an alternative to YouTube or YouTube Music.
    """

    ytsearch = "ytsearch"
    ytmsearch = "ytmsearch"
    scsearch = "scsearch"
    amsearch = "amsearch"

    def __str__(self) -> str:
        return self.value


class NodeAlgorithm(Enum):
    """The enum for the different node algorithms in Cytechlink.

    The enums in this class are to only differentiate different
    methods, since the actual method is handled in the
    get_best_node() method.

    NodeAlgorithm.by_ping returns a node based on it's latency,
    preferring a node with the lowest response time

    NodeAlgorithm.by_region returns a node based on its voice region,
    which the region is specified by the user in the method as an arg.
    This method will only work if you set a voice region when you create a node.
    """

    # We don't have to define anything special for these, since these just serve as flags
    by_ping = auto()
    by_region = auto()

    def __str__(self) -> str:
        return self.value
