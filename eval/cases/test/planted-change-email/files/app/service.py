"""Application service tying the repositories together."""

from app.users import get_user_display_name
from app.validators import is_valid_email, normalise_email


class AccountService:
    def __init__(self, users, orders):
        self.users = users
        self.orders = orders

    def register(self, user):
        if not is_valid_email(user.email):
            raise ValueError("invalid email address")
        user.email = normalise_email(user.email)
        return self.users.add(user)

    def summary_for(self, user_id):
        """A short summary line for a user."""
        name = get_user_display_name(self.users, user_id)
        total = self.orders.total_for_user(user_id)
        return f"{name} has spent {total / 100:.2f}"

    def deactivate(self, user_id):
        user = self.users.find_by_id(user_id)
        if user is None:
            return False
        user.is_active = False
        return True

    def change_email(self, user_id, email):
        """Let a user change their email address."""
        user = self.users.find_by_id(user_id)
        if user is None:
            return False
        user.email = email
        return True
