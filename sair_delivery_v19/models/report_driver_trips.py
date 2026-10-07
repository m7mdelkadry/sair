from odoo import models


class ReportSairDriverTrips(models.AbstractModel):
    _name = 'report.sair_delivery_v19.report_driver_trips'
    _description = 'تقرير كشف رحلات السائق التكيفي'

    def _get_report_values(self, docids, data=None):
        wizards = self.env['sair.driver.trips.wizard'].browse(docids)

        reports_data = []
        for wiz in wizards:
            rep = wiz._compute_report_data()
            reports_data.append(rep)

        return {
            'doc_ids': docids,
            'doc_model': 'sair.driver.trips.wizard',
            'docs': wizards,
            'reports_data': reports_data,
        }
