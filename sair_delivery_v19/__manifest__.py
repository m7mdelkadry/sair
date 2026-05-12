{
    'name': 'السير المتصل - نظام التوصيل',
    'version': '19.0.1.9.0',
    'category': 'Operations/Fleet',
    'summary': 'إدارة رحلات + تسوية + فواتير + عمولة + مراكز تكلفة + تقرير أداء السيارة',
    'author': 'Rashad',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'account', 'analytic', 'fleet', 'hr', 'l10n_sa'],
    'data': [
        'security/ir.model.access.csv',

        'data/sequences.xml',

        'reports/settlement_report.xml',
        'reports/invoice_report.xml',
        'reports/performance_report.xml',

        'views/sair_trip_views.xml',
        'views/sair_amana_views.xml',
        'views/sair_driver_expense_views.xml',
        'views/sair_office_commission_views.xml',
        'views/sair_settlement_views.xml',
        'views/fleet_vehicle_views.xml',

        'wizards/customer_statement_wizard_views.xml',
        'wizards/performance_wizard_views.xml',

        'views/sair_settings_views.xml',
        'views/sair_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
