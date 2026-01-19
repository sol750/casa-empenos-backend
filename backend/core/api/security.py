from rest_framework.exceptions import PermissionDenied

from core.models_security import UserRole, UserBranchAccess


def get_user_roles(user) -> set[str]:
    return set(
        UserRole.objects.filter(user=user).values_list("role__code", flat=True)
    )


def require_roles(user, allowed_roles: set[str]) -> set[str]:
    roles = get_user_roles(user)
    if not roles.intersection(allowed_roles):
        raise PermissionDenied("No tiene permisos.")
    return roles


def require_branch_access(user, branch_id: int) -> None:
    roles = get_user_roles(user)
    if "OWNER_ADMIN" in roles:
        return

    ok = UserBranchAccess.objects.filter(user=user, branch_id=branch_id).exists()
    if not ok:
        raise PermissionDenied("No tiene acceso a esta sucursal.")

