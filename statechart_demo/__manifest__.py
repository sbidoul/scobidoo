# Copyright 2019 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Statechart Demo',
    'summary': """Statechart Demo module""",
    'version': '13.0.1.0.0',
    'license': 'LGPL-3',
    'author': 'ACSONE SA/NV',
    'website': 'https://acsone.eu/',
    'depends': [
        'account',
        'statechart',
    ],
    'data': [
        'views/account_move.xml',
    ],
    'post_init_hook': 'init_sc_state',
}
