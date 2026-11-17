import unittest
from unittest.mock import patch
import postgres_ai_service as service

class TestPostgresAIService(unittest.TestCase):
    def test_no_tables_does_not_call_ai(self):
        with patch.object(service, 'describe_workspace', return_value=None), patch.object(service, 'generate_ai_response') as ai:
            self.assertEqual(service.ask_postgres('show data', 9001, 'dummy')['status'], 'clarification_needed')
            ai.assert_not_called()

    def test_success_uses_restricted_executor(self):
        with patch.object(service, 'describe_workspace', return_value='Table: "workspace_9001"."employees"\n- "id" INTEGER'), \
             patch.object(service, 'generate_ai_response', return_value='SELECT "id" FROM "workspace_9001"."employees"'), \
             patch.object(service, 'execute_restricted_select', return_value={'columns':['id'], 'rows':[[1]]}) as execute:
            result = service.ask_postgres('show ids', 9001, 'dummy')
            self.assertEqual(result['status'], 'success')
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[1:], (9001, 'dummy'))

    def test_other_workspace_rejected(self):
        with patch.object(service, 'describe_workspace', return_value='Table: "workspace_9001"."employees"'), \
             patch.object(service, 'generate_ai_response', return_value='SELECT * FROM "workspace_9002"."private_data"'), \
             patch.object(service, 'execute_restricted_select') as execute:
            with self.assertRaises(ValueError):
                service.ask_postgres('show private', 9001, 'dummy')
            execute.assert_not_called()

if __name__ == '__main__': unittest.main()
