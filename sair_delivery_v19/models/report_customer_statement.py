from odoo import models


class ReportSairCustomerStatement(models.AbstractModel):
    _name = 'report.sair_delivery_v19.report_customer_statement'
    _description = 'تقرير كشف رحلات العميل'

    def _get_report_values(self, docids, data=None):
        """
        يجهز البيانات للتمبلت من الويزرد
        """
        wizards = self.env['sair.customer.statement.wizard'].browse(docids)

        statements = []
        for wiz in wizards:
            stmt_data = wiz._compute_statement_lines()
            statements.append(stmt_data)

        return {
            'doc_ids': docids,
            'doc_model': 'sair.customer.statement.wizard',
            'docs': wizards,
            'statements': statements,
        }