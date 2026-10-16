from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify


class User(AbstractUser):
    """A CodeSage user, always originating from a GitHub OAuth login.

    `username` is inherited from AbstractUser and mirrors the GitHub login, but
    `github_id` is the stable identity: GitHub logins can be renamed, numeric ids
    cannot. Always match on `github_id`.

    The GitHub OAuth token is deliberately NOT stored. It is used once, during the
    callback, to read the user's profile and then discarded — everything that touches
    a repository goes through the GitHub App installation token instead (spec section 13),
    so there is no reason to keep a long-lived user credential in the database.
    """

    github_id = models.BigIntegerField(unique=True, null=True, blank=True)
    github_login = models.CharField(max_length=39, blank=True)
    avatar_url = models.URLField(blank=True)

    def __str__(self):
        return self.github_login or self.username


class Organization(models.Model):
    """A tenant. Repositories and reviews hang off an organisation, never off a user.

    Every user gets a personal organisation on first login so there is always exactly
    one tenant to attribute work to; shared organisations come later.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    is_personal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def generate_unique_slug(cls, name):
        """Slugify `name`, suffixing it until it does not collide.

        GitHub logins are unique, but organisation names are not, and the slug is
        user-visible in URLs — so collisions are resolved rather than raised.
        """
        base = slugify(name) or "org"
        slug = base
        suffix = 2
        while cls.objects.filter(slug=slug).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug


class Membership(models.Model):
    """Joins a user to an organisation with a role. The RBAC primitive."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"], name="unique_user_per_organization"
            )
        ]
        ordering = ["organization__name"]

    def __str__(self):
        return f"{self.user} in {self.organization} ({self.role})"
