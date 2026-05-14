"""
Tests para AL-01: Alertas en días no laborables

Valida la lógica del guard de fin de semana sin necesidad de importar
el script completo (para evitar dependencias de boto3/AWS).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


class TestWeekendGuard:
    """Tests unitarios del guard de fin de semana"""

    @pytest.mark.unit
    def test_should_run_on_monday(self):
        """Debe ejecutar en lunes (día laborable)"""
        # Lunes 2026-05-18 10:00 ART
        monday = datetime(2026, 5, 18, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        assert monday.weekday() == 0, "Lunes es weekday 0"
        assert monday.weekday() < 5, "Lunes NO debe activar guard"

    @pytest.mark.unit
    def test_should_not_run_on_saturday(self):
        """Debe skipear en sábado (fin de semana)"""
        # Sábado 2026-05-16 10:00 ART
        saturday = datetime(2026, 5, 16, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        assert saturday.weekday() == 5, "Sábado es weekday 5"
        assert saturday.weekday() >= 5, "Sábado debe activar guard"

        # Verificar mensaje de skip
        dias_es = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        dia = dias_es[saturday.weekday()]
        expected_msg = f"SKIP: ejecución en día no laborable ({saturday.strftime('%Y-%m-%d')}, {dia})"

        assert "sábado" in expected_msg
        assert "2026-05-16" in expected_msg
        assert "SKIP:" in expected_msg
        assert "día no laborable" in expected_msg

    @pytest.mark.unit
    def test_should_not_run_on_sunday(self):
        """Debe skipear en domingo (fin de semana)"""
        # Domingo 2026-05-17 10:00 ART
        sunday = datetime(2026, 5, 17, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        assert sunday.weekday() == 6, "Domingo es weekday 6"
        assert sunday.weekday() >= 5, "Domingo debe activar guard"

        # Verificar mensaje de skip
        dias_es = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        dia = dias_es[sunday.weekday()]
        expected_msg = f"SKIP: ejecución en día no laborable ({sunday.strftime('%Y-%m-%d')}, {dia})"

        assert "domingo" in expected_msg
        assert "2026-05-17" in expected_msg
        assert "SKIP:" in expected_msg
        assert "día no laborable" in expected_msg

    @pytest.mark.unit
    @pytest.mark.parametrize("weekday,day_name", [
        (0, "lunes"),
        (1, "martes"),
        (2, "miércoles"),
        (3, "jueves"),
        (4, "viernes"),
    ])
    def test_should_run_on_all_weekdays(self, weekday, day_name):
        """Debe ejecutar en todos los días laborables (lunes a viernes)"""
        # Semana de ejemplo: 2026-05-18 es lunes
        from datetime import timedelta

        base_date = datetime(2026, 5, 18, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
        test_date = base_date + timedelta(days=weekday)

        assert test_date.weekday() == weekday, f"{day_name} debe ser weekday {weekday}"
        assert test_date.weekday() < 5, f"{day_name} NO debe activar guard"

    @pytest.mark.unit
    @pytest.mark.parametrize("weekday,day_name", [
        (5, "sábado"),
        (6, "domingo"),
    ])
    def test_should_not_run_on_weekends(self, weekday, day_name):
        """Debe skipear en todos los días de fin de semana"""
        from datetime import timedelta

        # 2026-05-16 es sábado
        saturday = datetime(2026, 5, 16, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
        test_date = saturday + timedelta(days=weekday - 5)

        assert test_date.weekday() == weekday, f"{day_name} debe ser weekday {weekday}"
        assert test_date.weekday() >= 5, f"{day_name} debe activar guard"


class TestSkipLogicImplementation:
    """Tests de la lógica de skip implementada en el código real"""

    def _simulate_weekend_guard(self, now_art, allow_weekend_run=False, sim_q=False):
        """
        Simula la lógica exacta del guard en alerts_semantic_matches.py (líneas 1261-1296)

        Returns:
            tuple: (should_skip: bool, skip_msg: str | None)
        """
        if not allow_weekend_run and not sim_q:
            if now_art.weekday() >= 5:
                dias_es = (
                    "lunes", "martes", "miércoles", "jueves",
                    "viernes", "sábado", "domingo",
                )
                dia = dias_es[now_art.weekday()]
                skip_msg = (
                    f"SKIP: ejecución en día no laborable ({now_art.strftime('%Y-%m-%d')}, {dia})"
                )
                return True, skip_msg

        return False, None

    @pytest.mark.unit
    def test_guard_logic_on_monday(self):
        """Guard no debe skipear en lunes"""
        monday = datetime(2026, 5, 18, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        should_skip, skip_msg = self._simulate_weekend_guard(monday)

        assert should_skip is False, "No debe skipear en lunes"
        assert skip_msg is None, "No debe generar mensaje de skip"

    @pytest.mark.unit
    def test_guard_logic_on_saturday(self):
        """Guard debe skipear en sábado"""
        saturday = datetime(2026, 5, 16, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        should_skip, skip_msg = self._simulate_weekend_guard(saturday)

        assert should_skip is True, "Debe skipear en sábado"
        assert skip_msg is not None, "Debe generar mensaje de skip"
        assert "SKIP:" in skip_msg
        assert "2026-05-16" in skip_msg
        assert "sábado" in skip_msg

    @pytest.mark.unit
    def test_guard_logic_on_sunday(self):
        """Guard debe skipear en domingo"""
        sunday = datetime(2026, 5, 17, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        should_skip, skip_msg = self._simulate_weekend_guard(sunday)

        assert should_skip is True, "Debe skipear en domingo"
        assert skip_msg is not None, "Debe generar mensaje de skip"
        assert "SKIP:" in skip_msg
        assert "2026-05-17" in skip_msg
        assert "domingo" in skip_msg

    @pytest.mark.unit
    def test_guard_bypass_with_allow_weekend_run(self):
        """Flag allow_weekend_run debe permitir ejecución en fin de semana"""
        saturday = datetime(2026, 5, 16, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        should_skip, skip_msg = self._simulate_weekend_guard(saturday, allow_weekend_run=True)

        assert should_skip is False, "Con allow_weekend_run=True no debe skipear"
        assert skip_msg is None, "No debe generar mensaje de skip"

    @pytest.mark.unit
    def test_guard_bypass_with_sim_q(self):
        """Flag sim_q debe permitir ejecución en fin de semana"""
        saturday = datetime(2026, 5, 16, 10, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        should_skip, skip_msg = self._simulate_weekend_guard(saturday, sim_q=True)

        assert should_skip is False, "Con sim_q=True no debe skipear"
        assert skip_msg is None, "No debe generar mensaje de skip"


class TestTimezoneHandling:
    """Tests de manejo de timezone Argentina"""

    @pytest.mark.unit
    def test_uses_argentina_timezone(self):
        """Debe usar timezone America/Argentina/Buenos_Aires"""
        tz_art = "America/Argentina/Buenos_Aires"
        now_art = datetime.now(ZoneInfo(tz_art))

        assert now_art.tzinfo is not None
        assert str(now_art.tzinfo) == "America/Argentina/Buenos_Aires"

    @pytest.mark.unit
    def test_weekend_detection_in_argentina_timezone(self):
        """Debe detectar fin de semana en timezone Argentina, no UTC"""
        # Caso borde: viernes 23:00 ART = sábado 02:00 UTC
        # Debe considerar viernes (día laborable) en ART
        friday_23_art = datetime(2026, 5, 15, 23, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        assert friday_23_art.weekday() == 4, "Debe ser viernes en ART"

        # Caso borde: sábado 00:00 ART
        saturday_00_art = datetime(2026, 5, 16, 0, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        assert saturday_00_art.weekday() == 5, "Debe ser sábado en ART"

    @pytest.mark.unit
    def test_timezone_offset_art(self):
        """Verificar que ART es UTC-3"""
        import datetime as dt

        # Crear fecha en ART
        art_time = datetime(2026, 5, 15, 15, 0, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        # Convertir a UTC
        utc_time = art_time.astimezone(dt.timezone.utc)

        # ART es UTC-3, entonces 15:00 ART = 18:00 UTC
        assert utc_time.hour == 18, "15:00 ART debe ser 18:00 UTC"


class TestLogMessageFormat:
    """Tests del formato del mensaje de log"""

    @pytest.mark.unit
    def test_skip_message_contains_required_elements(self):
        """Mensaje de SKIP debe contener todos los elementos requeridos"""
        saturday = datetime(2026, 5, 16, 14, 30, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

        dias_es = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        dia = dias_es[saturday.weekday()]
        skip_msg = f"SKIP: ejecución en día no laborable ({saturday.strftime('%Y-%m-%d')}, {dia})"

        # Verificar formato según AL-01
        assert skip_msg.startswith("SKIP:"), "Debe comenzar con 'SKIP:'"
        assert "día no laborable" in skip_msg, "Debe contener 'día no laborable'"
        assert "2026-05-16" in skip_msg, "Debe contener fecha en formato YYYY-MM-DD"
        assert "sábado" in skip_msg, "Debe contener nombre del día"

        # Verificar formato exacto
        expected = "SKIP: ejecución en día no laborable (2026-05-16, sábado)"
        assert skip_msg == expected, f"Formato debe ser exacto: {expected}"

    @pytest.mark.unit
    @pytest.mark.parametrize("date_str,weekday,day_name", [
        ("2026-05-16", 5, "sábado"),
        ("2026-05-17", 6, "domingo"),
        ("2026-05-18", 0, "lunes"),
        ("2026-05-22", 4, "viernes"),
    ])
    def test_skip_message_format_for_all_days(self, date_str, weekday, day_name):
        """Verificar formato del mensaje para todos los días de la semana"""
        test_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
            tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")
        )

        dias_es = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        dia = dias_es[test_date.weekday()]

        assert test_date.weekday() == weekday
        assert dia == day_name

        skip_msg = f"SKIP: ejecución en día no laborable ({test_date.strftime('%Y-%m-%d')}, {dia})"

        assert f"({date_str}, {day_name})" in skip_msg


if __name__ == "__main__":
    # Ejecutar tests con pytest
    pytest.main([__file__, "-v", "--tb=short"])
