from rest_framework.exceptions import PermissionDenied

from core.models_security import UserRole, UserBranchAccess


OWNER_ROLE = "OWNER_ADMIN"


def get_user_roles(user) -> set[str]:
    return set(
        UserRole.objects.filter(user=user).values_list("role__code", flat=True)
    )


def is_owner_admin(user) -> bool:
    return OWNER_ROLE in get_user_roles(user)


def get_user_branch_codes(user) -> set[str]:
    return set(
        UserBranchAccess.objects.filter(user=user).values_list("branch__code", flat=True)
    )


def require_roles(user, allowed_roles: set[str]) -> set[str]:
    roles = get_user_roles(user)
    if not roles.intersection(allowed_roles):
        raise PermissionDenied("No tiene permisos.")
    return roles


def require_branch_access(user, branch_id: int) -> None:
    """
    Lanza PermissionDenied (403) si el usuario no tiene acceso a la sucursal.
    OWNER_ADMIN pasa siempre.
    """
    if is_owner_admin(user):
        return

    ok = UserBranchAccess.objects.filter(user=user, branch_id=branch_id).exists()
    if not ok:
        raise PermissionDenied("No tiene acceso a esta sucursal.")
