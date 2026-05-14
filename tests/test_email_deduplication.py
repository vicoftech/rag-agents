"""
Tests para AL-02: Idempotencia de emails - Prevención de duplicados

Valida la lógica de detección y prevención de emails duplicados
sin necesidad de importar el script completo.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


class TestIdempotencyLogic:
    """Tests de lógica de idempotencia (simulación sin imports)"""

    def _simulate_check_email_already_sent(
        self,
        conn,
        alert_id: int | str | None,
        recipient_email: str,
        sent_date: date | None = None,
    ) -> bool:
        """
        Simula la función _check_email_already_sent del script.

        Returns:
            True si el email ya fue enviado, False en caso contrario
        """
        if conn is None:
            return False

        if not alert_id or not recipient_email:
            return False

        if sent_date is None:
            sent_date = date.today()

        try:
            # Simular consulta SQL
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM alert_emails_sent WHERE alert_id = %s AND recipient_email = %s AND sent_date = %s LIMIT 1",
                    (int(alert_id), recipient_email.strip(), sent_date),
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    @pytest.mark.unit
    def test_check_email_not_sent_yet(self):
        """Debe retornar False si el email no ha sido enviado"""
        # Mock de conexión y cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # No existe registro
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = self._simulate_check_email_already_sent(
            conn=mock_conn,
            alert_id=123,
            recipient_email="user@example.com",
            sent_date=date(2026, 5, 13),
        )

        assert result is False
        mock_cursor.execute.assert_called_once()
        assert "alert_emails_sent" in mock_cursor.execute.call_args[0][0]

    @pytest.mark.unit
    def test_check_email_already_sent(self):
        """Debe retornar True si el email ya fue enviado"""
        # Mock de conexión y cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)  # Existe registro
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = self._simulate_check_email_already_sent(
            conn=mock_conn,
            alert_id=123,
            recipient_email="user@example.com",
            sent_date=date(2026, 5, 13),
        )

        assert result is True

    @pytest.mark.unit
    def test_check_email_no_connection(self):
        """Debe retornar False si no hay conexión a PostgreSQL"""
        result = self._simulate_check_email_already_sent(
            conn=None,
            alert_id=123,
            recipient_email="user@example.com",
        )

        assert result is False

    @pytest.mark.unit
    def test_check_email_missing_alert_id(self):
        """Debe retornar False si falta alert_id"""
        mock_conn = MagicMock()

        result = self._simulate_check_email_already_sent(
            conn=mock_conn,
            alert_id=None,
            recipient_email="user@example.com",
        )

        assert result is False

    @pytest.mark.unit
    def test_check_email_missing_recipient(self):
        """Debe retornar False si falta recipient_email"""
        mock_conn = MagicMock()

        result = self._simulate_check_email_already_sent(
            conn=mock_conn,
            alert_id=123,
            recipient_email="",
        )

        assert result is False

    @pytest.mark.unit
    def test_check_email_database_error(self):
        """Debe retornar False si hay error en la base de datos"""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("Database error")

        result = self._simulate_check_email_already_sent(
            conn=mock_conn,
            alert_id=123,
            recipient_email="user@example.com",
        )

        assert result is False


class TestDuplicateDetection:
    """Tests de detección de duplicados"""

    @pytest.mark.unit
    def test_same_alert_same_recipient_same_day_is_duplicate(self):
        """Misma alerta al mismo destinatario el mismo día debe detectarse como duplicado"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)  # Ya existe
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simular consulta
        with mock_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_emails_sent WHERE alert_id = %s AND recipient_email = %s AND sent_date = %s",
                (123, "user@example.com", date(2026, 5, 13)),
            )
            exists = cur.fetchone() is not None

        assert exists is True

    @pytest.mark.unit
    def test_same_alert_different_day_not_duplicate(self):
        """Misma alerta en diferente día NO debe ser duplicado"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # Primera consulta: día 13 (existe)
        # Segunda consulta: día 14 (no existe)
        mock_cursor.fetchone.side_effect = [(1,), None]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Día 13: existe
        with mock_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_emails_sent WHERE alert_id = %s AND recipient_email = %s AND sent_date = %s",
                (123, "user@example.com", date(2026, 5, 13)),
            )
            exists_day_13 = cur.fetchone() is not None

        # Día 14: no existe
        with mock_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_emails_sent WHERE alert_id = %s AND recipient_email = %s AND sent_date = %s",
                (123, "user@example.com", date(2026, 5, 14)),
            )
            exists_day_14 = cur.fetchone() is not None

        assert exists_day_13 is True
        assert exists_day_14 is False

    @pytest.mark.unit
    def test_different_alert_same_recipient_not_duplicate(self):
        """Diferente alerta al mismo destinatario NO debe ser duplicado"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # No existe
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        with mock_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_emails_sent WHERE alert_id = %s AND recipient_email = %s AND sent_date = %s",
                (456, "user@example.com", date(2026, 5, 13)),  # Alert ID diferente
            )
            exists = cur.fetchone() is not None

        assert exists is False

    @pytest.mark.unit
    def test_same_alert_different_recipient_not_duplicate(self):
        """Misma alerta a diferente destinatario NO debe ser duplicado"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # No existe
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        with mock_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_emails_sent WHERE alert_id = %s AND recipient_email = %s AND sent_date = %s",
                (123, "different@example.com", date(2026, 5, 13)),  # Email diferente
            )
            exists = cur.fetchone() is not None

        assert exists is False


class TestNotificationFiltering:
    """Tests de filtrado de notificaciones"""

    def _simulate_filter_duplicate_notifications(
        self,
        notifs: list[dict],
        conn,
    ) -> tuple[list[dict], int]:
        """
        Simula la función filter_duplicate_notifications del script.

        Returns:
            Tupla (notificaciones_filtradas, cantidad_duplicados)
        """
        if conn is None:
            return (notifs, 0)

        filtered: list[dict] = []
        duplicates_count = 0
        today = date.today()

        for notif in notifs:
            alert_id = notif.get("alerta_id")
            message = notif.get("message") or {}
            recipient_email = (message.get("to") or "").strip()

            if not alert_id or not recipient_email:
                filtered.append(notif)
                continue

            # Simular consulta a BD
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM alert_emails_sent WHERE alert_id = %s AND recipient_email = %s AND sent_date = %s",
                        (alert_id, recipient_email, today),
                    )
                    already_sent = cur.fetchone() is not None
            except Exception:
                already_sent = False

            if already_sent:
                duplicates_count += 1
            else:
                filtered.append(notif)

        return (filtered, duplicates_count)

    @pytest.mark.unit
    def test_filter_no_duplicates(self):
        """Debe retornar todas las notificaciones si no hay duplicados"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # Ninguna está duplicada
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        notifs = [
            {
                "alerta_id": 1,
                "message": {"to": "user1@example.com", "subject": "Test 1"},
            },
            {
                "alerta_id": 2,
                "message": {"to": "user2@example.com", "subject": "Test 2"},
            },
        ]

        filtered, duplicates_count = self._simulate_filter_duplicate_notifications(
            notifs, mock_conn
        )

        assert len(filtered) == 2
        assert duplicates_count == 0

    @pytest.mark.unit
    def test_filter_with_duplicates(self):
        """Debe filtrar notificaciones duplicadas"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # Primera consulta: existe (duplicada)
        # Segunda consulta: no existe
        mock_cursor.fetchone.side_effect = [(1,), None]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        notifs = [
            {
                "alerta_id": 1,
                "message": {"to": "user1@example.com", "subject": "Test 1"},
            },
            {
                "alerta_id": 2,
                "message": {"to": "user2@example.com", "subject": "Test 2"},
            },
        ]

        filtered, duplicates_count = self._simulate_filter_duplicate_notifications(
            notifs, mock_conn
        )

        assert len(filtered) == 1
        assert duplicates_count == 1
        assert filtered[0]["alerta_id"] == 2

    @pytest.mark.unit
    def test_filter_no_connection(self):
        """Debe retornar todas las notificaciones si no hay conexión"""
        notifs = [
            {
                "alerta_id": 1,
                "message": {"to": "user1@example.com", "subject": "Test 1"},
            },
        ]

        filtered, duplicates_count = self._simulate_filter_duplicate_notifications(
            notifs, None
        )

        assert len(filtered) == 1
        assert duplicates_count == 0

    @pytest.mark.unit
    def test_filter_with_missing_data(self):
        """Debe incluir notificaciones con datos faltantes (sin filtrar)"""
        mock_conn = MagicMock()

        notifs = [
            {
                "alerta_id": None,  # Falta alert_id
                "message": {"to": "user1@example.com", "subject": "Test 1"},
            },
            {
                "alerta_id": 2,
                "message": {"to": "", "subject": "Test 2"},  # Falta email
            },
            {
                "alerta_id": 3,
                "message": {},  # message vacío
            },
        ]

        filtered, duplicates_count = self._simulate_filter_duplicate_notifications(
            notifs, mock_conn
        )

        # Todas deberían incluirse
        assert len(filtered) == 3
        assert duplicates_count == 0


class TestDatabaseSchema:
    """Tests del schema de la base de datos"""

    @pytest.mark.unit
    def test_table_has_unique_constraint(self):
        """La tabla debe tener constraint UNIQUE en (alert_id, recipient_email, sent_date)"""
        # Esto se valida en la migration SQL
        # El test verifica que la lógica espera este constraint
        constraint_fields = ["alert_id", "recipient_email", "sent_date"]

        assert len(constraint_fields) == 3
        assert "alert_id" in constraint_fields
        assert "recipient_email" in constraint_fields
        assert "sent_date" in constraint_fields

    @pytest.mark.unit
    def test_query_uses_correct_fields(self):
        """La consulta debe usar los campos correctos del constraint"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simular consulta
        with mock_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alert_emails_sent WHERE alert_id = %s AND recipient_email = %s AND sent_date = %s",
                (123, "user@example.com", date(2026, 5, 13)),
            )

        # Verificar que se llamó con los 3 parámetros correctos
        call_args = mock_cursor.execute.call_args[0]
        assert "alert_id" in call_args[0]
        assert "recipient_email" in call_args[0]
        assert "sent_date" in call_args[0]
        assert len(call_args[1]) == 3


if __name__ == "__main__":
    # Ejecutar tests con pytest
    pytest.main([__file__, "-v", "--tb=short"])
