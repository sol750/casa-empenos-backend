from django.conf import settings
from django.db import models


class Role(models.Model):
    """
    Roles del sistema.
    """
    code = models.CharField(max_length=30, unique=True)  # CAJERO, SUPERVISOR, OWNER_ADMIN, AUDITOR
    name = models.CharField(max_length=60)

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self) -> str:
        return self.code


class UserRole(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_roles")

    class Meta:
        verbose_name = "Rol de Usuario"
        verbose_name_plural = "Roles de Usuario"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="unique_user_role")
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.role}"


class UserBranchAccess(models.Model):
    """
    Define a qué sucursales puede acceder un usuario.
    OWNER_ADMIN y AUDITOR normalmente tendrán acceso a todas, pero igual lo dejamos explícito.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="branch_access")
    branch = models.ForeignKey("core.Branch", on_delete=models.PROTECT, related_name="user_access")

    class Meta:
        verbose_name = "Acceso a Sucursal"
        verbose_name_plural = "Accesos a Sucursales"
        constraints = [
            models.UniqueConstraint(fields=["user", "branch"], name="unique_user_branch_access")
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.branch.code}"
