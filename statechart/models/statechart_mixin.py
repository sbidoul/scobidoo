# Copyright 2016-2018 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import json
import logging

from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import MissingError

from .event import Event
from .interpreter import Interpreter
from ..exceptions import NoTransitionError

_logger = logging.getLogger(__name__)


def _sc_make_event_allowed_field_name(event_name):
    # TODO event names must be valid python identifiers
    #      (that must be tested somewhere long before reaching this point)
    return 'sc_' + event_name + '_allowed'


def _sc_is_event_allowed_field_name(field_name):
    return (
        field_name.startswith('sc_') and
        field_name.endswith('_allowed')
    )


def _sc_event_from_event_allowed_field_name(field_name):
    return field_name[3:-8]


class InterpreterField(fields.Field):
    type = 'sc_interpreter'


class StatechartMixin(models.AbstractModel):

    _name = 'statechart.mixin'
    _description = 'Statechart Mixin'

    # TODO if we want this to be configurable through the Odoo UI
    #      this mixin probably must go away and the register_hook
    #      must run for all models that have a statechart;
    #      this is much easier to do in Odoo 10+ by inheriting
    #      BaseModel though.
    #
    #      That said, if we get rid of this mixin, we must find
    #      a better way to cache interpreters; this is currently
    #      implemented with the sc_interpreter special field.

    sc_state = fields.Char(
        copy=False,
    )
    sc_interpreter = InterpreterField(
        compute='_compute_sc_interpreter')
    sc_display_state = fields.Char(
        compute='_compute_sc_display_state')

    @api.multi
    def sc_queue(self, event_name, *args, **kwargs):
        for rec in self:
            interpreter = rec.sc_interpreter
            event = Event(event_name, args=args, kwargs=kwargs)
            _logger.debug("=> queueing event %s for %s", event, rec)
            interpreter.queue(event)
            if not interpreter.executing:
                rec._sc_execute(interpreter, event)

    @api.depends('sc_state')
    def _compute_sc_interpreter(self):
        statechart = self._statechart
        for rec in self:
            _logger.debug("initializing interpreter for %s", rec)
            initial_context = {
                'o': rec,
                # TODO: more action context
            }
            interpreter = Interpreter(
                statechart, initial_context=initial_context)
            if rec.sc_state:
                config = json.loads(rec.sc_state)
                interpreter.restore_configuration(config)
            else:
                interpreter.execute_once()
            rec.sc_interpreter = interpreter

    @api.depends('sc_state')
    def _compute_sc_display_state(self):
        # TODO
        for rec in self:
            rec.sc_display_state = rec.sc_state

    @api.multi
    def _sc_execute(self, interpreter, orig_event):
        self.ensure_one()
        steps = interpreter.execute()
        _logger.debug("<= %s", steps)
        if not all([step.transitions for step in steps]):
            # at least one step had no transition => error
            raise NoTransitionError(
                _("This action is not allowed in the current state "
                  "or with your access rights.\n\n"
                  "Technical details of the error: %s\nSteps: %s") %
                (orig_event, steps,))
        config = interpreter.save_configuration()
        new_sc_state = json.dumps(config)
        try:
            # TODO converting to json to determine if sc_state
            #      has changed is not optimal
            if new_sc_state != self.sc_state:
                self.write({'sc_state': new_sc_state})
        except MissingError:  # pylint: disable=except-pass
            # object has been deleted so don't attempt to set its state
            pass

    @api.multi
    def _sc_exec_event(self, event_name, *args, **kwargs):
        for rec in self:
            interpreter = rec.sc_interpreter
            if not interpreter.executing:
                event = Event(event_name, args=args, kwargs=kwargs)
                _logger.debug("=> queueing event %s for %s", event, rec)
                interpreter.queue(event)
                rec._sc_execute(interpreter, event)
                if len(self) == 1 and event._return:
                    return event._return
            else:
                event = Event(event_name, args=args, kwargs=kwargs)
                msg = _(
                    "Reentrancy error for %s on %s. "
                    "Please use sc_queue() "
                    "instead of a direct method call. "
                ) % (event, rec)
                raise RuntimeError(msg)
        return None

    @api.depends('sc_state')
    def _compute_sc_event_allowed(self):
        # TODO depends() is partial (it does not know the dependencies of
        #      guards): make sure that works in all practical situations
        statechart = self._statechart
        event_names = statechart.events_for()
        for rec in self:
            interpreter = rec.sc_interpreter
            for event_name in event_names:
                field_name = _sc_make_event_allowed_field_name(event_name)
                allowed = interpreter.is_event_allowed(event_name)
                if allowed is None:
                    # None means a guard could not be evaluated: since
                    # we don't know if it's allowed, report it as allowed
                    # and the user may receive an error message later
                    # if he tries to do the action
                    allowed = True
                setattr(rec, field_name, allowed)

    @api.model
    def fields_view_get(self, view_id=None, view_type='form',
                        context=None, toolbar=False, submenu=False):
        # Override fields_view_get to automatically add
        # the sc_<event>_allowed fields to form view. This is necessary
        # because the views are loaded before _register_hook so our
        # runtime-added fields are not present at that time.
        # This is also a shortcut for the developper who does
        # not need to add them manually in the views.
        # TODO we could go further and automatically make buttons
        #      that trigger events visible or not; this is a bit
        #      more (too much?) magical
        result = super(StatechartMixin, self).fields_view_get(
            view_id=view_id, view_type=view_type,
            toolbar=toolbar, submenu=submenu)
        if view_type != 'form':
            return result
        statechart = self._statechart
        fields_by_name = result['fields']
        doc = etree.XML(result['arch'])
        form = doc.xpath('/form')[0]
        view = self.env['ir.ui.view'].search([('id', '=', result['view_id'])])
        for event_name in statechart.events_for():
            field_name = _sc_make_event_allowed_field_name(event_name)
            if field_name not in fields_by_name:
                fields_by_name[field_name] = {
                    'string': field_name,
                    'type': 'boolean',
                }
                new_node = etree.Element("field", {
                    "name": field_name,
                    "invisible": "1",
                })
                form.append(new_node)
                view.postprocess(result['model'], new_node, view_id, False,
                                 result['fields'])
        result['arch'] = etree.tostring(doc)
        return result

    @api.model
    def create(self, vals):
        rec = super(StatechartMixin, self).create(vals)
        # make sure the interpreter is initialized, because
        # merely entering the root state may have side effects
        # (onentry, etc) and we don't want that to occur
        # more than once
        config = rec.sc_interpreter.save_configuration()
        rec.sc_state = json.dumps(config)
        return rec

    @api.model
    def default_get(self, fields_list):
        """ Get default values for sc_event_allowed fields.

        To compute this we instanciate a dummy interpreter. This implies
        entering the initial state and executing the associated actions.
        It is therefore important that such actions have no side effects.
        """
        res = super(StatechartMixin, self).default_get(fields_list)
        dummy_interpreter = None
        for field in fields_list:
            if _sc_is_event_allowed_field_name(field):
                if not dummy_interpreter:
                    dummy = self.new()
                    dummy_interpreter = dummy.sc_interpreter
                event_name = _sc_event_from_event_allowed_field_name(field)
                default = dummy_interpreter.is_event_allowed(event_name)
                res[field] = default
        return res
