APP_NAME = "KCD2 ModMaster"
APP_ID = "PAWSKI.KCD2ModMaster"
VERSION = "0.9.7"
CHANNEL = "beta"
PUBLISHER = "PAWSKI"
HOMEPAGE = "https://realpawski.de/releases/"
REPOSITORY = "realpawski/KCD2-ModMaster"


def display_version() -> str:
    return f"{VERSION} {CHANNEL.title()}" if CHANNEL else VERSION
