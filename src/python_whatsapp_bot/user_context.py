from typing import Any, Dict


class _Context:
    """Object to store all users data in a conversation"""

    def __init__(self):
        # type: () -> None
        self.users_data = {}  # type: Dict[str, Dict[str, Any]]

    def _add_user(self, phone_num):
        # type: (str) -> None
        self.users_data[str(phone_num)] = {}

    def _user_exists(self, phone_num):
        # type: (str) -> bool
        if len(self.users_data):
            if phone_num in self.users_data.keys():
                return True
        return False


_context = _Context()


class User_context():
    """Object that manages a specific user's data in a conversation.
    The user's phone number id is used as the id"""

    def __init__(self, phone_num):
        # type: (str) -> None
        if not _context._user_exists(phone_num):
            _context._add_user(phone_num)
        self.user_data = _context.users_data[str(phone_num)]  # type: Dict[str, Any]

    # def user_data(self):
    #     pass
