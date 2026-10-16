from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import Membership, Organization, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ["username", "github_login", "github_id", "email", "is_staff"]
    search_fields = ["username", "github_login", "email"]
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("GitHub", {"fields": ("github_id", "github_login", "avatar_url")}),
    )


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_personal", "created_at"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organization", "role", "created_at"]
    list_filter = ["role"]
    search_fields = ["user__username", "organization__name"]
    autocomplete_fields = ["user", "organization"]
