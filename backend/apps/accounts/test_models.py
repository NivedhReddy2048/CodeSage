"""Model-level tests for the RBAC primitives and the org listing query shape."""

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Membership, Organization, User
from apps.accounts.services import create_personal_organization, get_or_create_user_from_github


def make_user(github_id, login):
    user, _ = get_or_create_user_from_github(
        {"id": github_id, "login": login, "name": "", "email": "", "avatar_url": ""}
    )
    return user


@pytest.mark.django_db
def test_a_user_cannot_join_the_same_org_twice():
    """The unique constraint is what stops duplicate, conflicting roles."""
    user = make_user(1, "one")
    organization = user.memberships.first().organization

    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.ADMIN)


@pytest.mark.django_db
def test_membership_defaults_to_member():
    """Only explicit promotion should grant more than the least privilege."""
    user = make_user(2, "two")
    other = Organization.objects.create(name="Shared", slug="shared")

    membership = Membership.objects.create(user=user, organization=other)

    assert membership.role == Membership.Role.MEMBER


@pytest.mark.django_db
def test_role_choices_are_the_three_rbac_levels():
    assert [role for role, _ in Membership.Role.choices] == ["owner", "admin", "member"]


@pytest.mark.django_db
def test_personal_org_owner_is_the_user():
    user = make_user(3, "three")

    membership = user.memberships.get()

    assert membership.role == Membership.Role.OWNER
    assert membership.organization.is_personal is True


@pytest.mark.django_db
def test_deleting_a_user_removes_their_memberships():
    user = make_user(4, "four")
    assert Membership.objects.count() == 1

    user.delete()

    assert Membership.objects.count() == 0


@pytest.mark.django_db
def test_slug_is_generated_from_a_name_with_awkward_characters():
    slug = Organization.generate_unique_slug("Nivedh's Team!! (2026)")

    assert slug and " " not in slug and "'" not in slug


@pytest.mark.django_db
def test_slug_falls_back_when_a_name_slugifies_to_nothing():
    """A login of only non-latin characters would otherwise produce an empty slug."""
    assert Organization.generate_unique_slug("!!!") == "org"


@pytest.mark.django_db
def test_org_list_does_not_scale_queries_with_org_count(django_assert_num_queries):
    """Guards the Subquery annotation against a later N+1 regression.

    The role for each organisation comes from an annotation precisely so that listing
    many organisations costs the same as listing one. Without it, the serializer would
    query per row.
    """
    user = make_user(5, "five")
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    url = reverse("organization-list")

    # Baseline with the single personal organisation.
    with django_assert_num_queries(2):
        assert len(client.get(url).json()) == 1

    for index in range(6):
        organization = Organization.objects.create(name=f"Team {index}", slug=f"team-{index}")
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.ADMIN)

    # Same query count with seven organisations: one for the user, one for the list.
    with django_assert_num_queries(2):
        assert len(client.get(url).json()) == 7


@pytest.mark.django_db
def test_org_list_reports_the_right_role_per_org():
    user = make_user(6, "six")
    shared = Organization.objects.create(name="Shared", slug="shared-two")
    Membership.objects.create(user=user, organization=shared, role=Membership.Role.ADMIN)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    body = client.get(reverse("organization-list")).json()

    roles = {entry["name"]: entry["role"] for entry in body}
    assert roles["Shared"] == "admin"
    assert roles["six's workspace"] == "owner"


@pytest.mark.django_db
def test_str_representations_are_useful_in_the_admin():
    user = make_user(7, "seven")
    membership = user.memberships.get()

    assert str(user) == "seven"
    assert "seven" in str(membership.organization)
    assert "owner" in str(membership)


@pytest.mark.django_db
def test_username_collisions_are_suffixed_until_free():
    """The rename path: someone else now holds the login a new account arrives with.

    Reachable when a GitHub account is renamed and a different account claims the
    freed-up login. Without the suffixing this raises IntegrityError mid-login.
    """
    # Occupy both "taken" and "taken-2" so the loop has to advance past them.
    User.objects.create(username="taken", github_id=900)
    User.objects.create(username="taken-2", github_id=901)

    user = make_user(902, "taken")

    assert user.username == "taken-3"
    # The GitHub login is recorded as-is; only the Django username is disambiguated.
    assert user.github_login == "taken"


@pytest.mark.django_db
def test_a_second_personal_org_for_the_same_user_is_possible_but_slugged_apart():
    """create_personal_organization is idempotent-free by design; slugs must not clash."""
    user = make_user(8, "eight")

    second = create_personal_organization(user)

    assert User.objects.count() == 1
    assert second.slug != user.memberships.first().organization.slug
