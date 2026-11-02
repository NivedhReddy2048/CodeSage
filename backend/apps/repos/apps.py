from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class ReposConfig(AppConfig):
    name = "apps.repos"

    def ready(self):
        from apps.repos import catchup
        from apps.repos.models import AppInstallation, Repository

        # The catch-up caches which repositories to visit. Connecting,
        # disconnecting, suspending or removing an installation drops that list.
        post_save.connect(catchup.repository_saved, sender=Repository, weak=False)
        post_save.connect(catchup.installation_saved, sender=AppInstallation, weak=False)
        for model in (Repository, AppInstallation):
            post_delete.connect(catchup.forget_repositories, sender=model, weak=False)
