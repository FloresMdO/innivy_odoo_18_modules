
# -*- coding: utf-8 -*-
from odoo import models, fields, api

class HiveConfig(models.Model):
    _name = 'hive.config'
    _description = "Hive Configuration"
    
    name = fields.Char(
        required=True
    )
    hive_url = fields.Char(
        string="HIVE API URL", 
        default='http://localhost:18790'
    )
    hive_token = fields.Char(
        string="HIVE AUTH TOKEN",
    )
    is_hive_enabled = fields.Boolean(
        string="ENABLED",
        readonly=False
    )
    hive_user_id = fields.Many2one(
        'res.partner',
        string="USER",
    )
