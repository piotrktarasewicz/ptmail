import keyring
from keyring.errors import PasswordDeleteError

from . import APP_NAME


def get_password(account):
    return keyring.get_password(APP_NAME, account.email)


def set_password(account, password):
    keyring.set_password(APP_NAME, account.email, password)


def delete_password(account):
    try:
        keyring.delete_password(APP_NAME, account.email)
    except PasswordDeleteError:
        pass
