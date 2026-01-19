from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction

from core.models import Branch, CashRegister
from core.models_security import Role, UserRole, UserBranchAccess


class Command(BaseCommand):
    help = "Seed inicial: roles, sucursales, cajas y usuario dev (idempotente)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("== Seed inicial START =="))

        # 1) Roles
        roles = [
            ("OWNER_ADMIN", "Dueño/Administrador"),
            ("SUPERVISOR", "Supervisor"),
            ("CAJERO", "Cajero"),
        ]
        for code, name in roles:
            Role.objects.get_or_create(code=code, defaults={"name": name})
        self.stdout.write(self.style.SUCCESS("Roles OK"))

        # 2) Sucursales
        branches_data = [
            ("PT1", "Potosi 1"),
            ("PT2", "Potosi 2"),
        ]
        branches = {}
        for code, name in branches_data:
            b, _ = Branch.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})
            branches[code] = b
        self.stdout.write(self.style.SUCCESS("Sucursales OK"))

        # 3) Cajas por sucursal (2 por sucursal)
        for code, branch in branches.items():
            CashRegister.objects.get_or_create(
                register_type=CashRegister.RegisterType.BRANCH,
                branch=branch,
                name="Caja 1",
                defaults={"is_active": True},
            )
            CashRegister.objects.get_or_create(
                register_type=CashRegister.RegisterType.BRANCH,
                branch=branch,
                name="Caja 2",
                defaults={"is_active": True},
            )
        self.stdout.write(self.style.SUCCESS("Cajas sucursal OK"))

        # 4) Caja global
        CashRegister.objects.get_or_create(
            register_type=CashRegister.RegisterType.GLOBAL,
            branch=None,
            name="Caja Dueño",
            defaults={"is_active": True},
        )
        self.stdout.write(self.style.SUCCESS("Caja global OK"))

        # 5) Usuario dev: dueno (solo para desarrollo)
        User = get_user_model()
        dueno, created = User.objects.get_or_create(
            username="dueno",
            defaults={"is_staff": True, "is_superuser": True},
        )
        if created:
            dueno.set_password("dueno1234")
            dueno.save()
            self.stdout.write(self.style.SUCCESS("Usuario dev 'dueno' creado (pass: dueno1234)"))
        else:
            self.stdout.write(self.style.WARNING("Usuario dev 'dueno' ya existía (no se cambió password)"))

        owner_role = Role.objects.get(code="OWNER_ADMIN")
        UserRole.objects.get_or_create(user=dueno, role=owner_role)

        for branch in branches.values():
            UserBranchAccess.objects.get_or_create(user=dueno, branch=branch)

        self.stdout.write(self.style.SUCCESS("Accesos dueño OK"))
        self.stdout.write(self.style.WARNING("== Seed inicial END =="))
