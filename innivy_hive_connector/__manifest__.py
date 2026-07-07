{
    "name": "Hive Connector",
    "version": "18.0.0.1",
    "author": "Innivy",
    "category": "Services",
    "summary": "Connect Odoo to Hive",
    "description": "Connect Odoo to Hive",
    "depends": ["base","mail"],
    "data": [
        'security/ir.model.access.csv',
        "views/hive_config_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}