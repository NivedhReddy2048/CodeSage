"""Account provisioning: GitHub profile in, User + personal Organization out."""

from django.db import transaction

from apps.accounts.models import Membership, Organization, User


@transaction.atomic
def get_or_create_user_from_github(profile):
    """Match or create a User from a GitHub profile dict.

    Returns `(user, created)`.

    Matching is on `github_id`, never on login or email: GitHub logins can be renamed
    and emails can change, but the numeric id is stable. Matching on login would hand
    an existing account to whoever claimed a freed-up username.

    A newly created user also gets a personal Organization owned by them, so there is
    always exactly one tenant available to attribute repositories and reviews to.
    """
    github_id = profile["id"]
    login = profile.get("login") or f"gh-{github_id}"

    user = User.objects.filter(github_id=github_id).first()

    if user is not None:
        # Refresh the mutable profile fields — the login may have been renamed since.
        user.github_login = login
        user.username = login
        user.avatar_url = profile.get("avatar_url") or ""
        if profile.get("email"):
            user.email = profile["email"]
        _apply_display_name(user, profile)
        user.save()
        return user, False

    user = User(
        username=_unique_username(login),
        github_id=github_id,
        github_login=login,
        email=profile.get("email") or "",
        avatar_url=profile.get("avatar_url") or "",
    )
    _apply_display_name(user, profile)
    # Login is via GitHub only; there is no password to authenticate against.
    user.set_unusable_password()
    user.save()

    create_personal_organization(user)
    return user, True


def _apply_display_name(user, profile):
    """Split GitHub's single free-text `name` into Django's first/last fields.

    GitHub has one name field; Django has two. Everything after the first space goes
    into last_name, which is wrong for some names but is the honest best guess from a
    single string, and only affects display.
    """
    full_name = (profile.get("name") or "").strip()
    if not full_name:
        return
    first, _, last = full_name.partition(" ")
    user.first_name = first[:150]
    user.last_name = last[:150]


def _unique_username(login):
    """Avoid colliding with an existing username.

    Only reachable when a GitHub account was renamed and a different account took the
    old login. Rare, but it would otherwise raise IntegrityError mid-login.
    """
    if not User.objects.filter(username=login).exists():
        return login
    suffix = 2
    while User.objects.filter(username=f"{login}-{suffix}").exists():
        suffix += 1
    return f"{login}-{suffix}"


def create_personal_organization(user):
    """Create the user's personal organisation and make them its owner."""
    display = user.github_login or user.username
    organization = Organization.objects.create(
        name=f"{display}'s workspace",
        slug=Organization.generate_unique_slug(display),
        is_personal=True,
    )
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
    return organization
