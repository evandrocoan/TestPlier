# -*- coding: utf-8 -*-
from copy import deepcopy
import os
import re

import sublime
import sublime_plugin

from debug_tools import getLogger

from . import utils
log = getLogger( 1, __name__, trimname=__package__ )

g_last_valid_kwargs = {}
g_last_function_class_names = {}


class NoTestFound(RuntimeError):
    """
        Throw when you are in a python file with no valid tests.
    """
    pass


class RunPythonTestsCommand(sublime_plugin.WindowCommand):
    external_runner = None

    def __init__(self, window=None):
        log._debugger_level = 3 if utils.DEBUG() else 1
        log(2, "Here on RunPythonTestsCommand constructor!")

        self.window_id = window.id()
        if window:
            log(2, "Here on RunPythonTestsCommand with window %s - id %s!" % (window, window.id()))
            super().__init__(window)

        else:
            self.window = sublime.active_window()
            super().__init__()

        settings = sublime.load_settings("TestPlier.sublime-settings")
        self.run_last_valid_test = settings.get('run_last_valid_test', False)

        if window.id() in g_last_function_class_names:
            log(2, "Here on RunPythonTestsCommand, the attributes are: %s" % str(g_last_function_class_names[self.window_id]))

        else:
            log(2, "Here on RunPythonTestsCommand DOES NOT HAVE THE ATTRIBUTES")
            g_last_function_class_names[self.window_id] = ('', '', '')

    def setup_runner(self):
        self.settings = sublime.load_settings("TestPlier.sublime-settings")
        log(2, "Settings: ", vars(self.settings))
        self.default_cmd = self.settings.get('default_cmd')
        log(2, "Default CMD: ", self.default_cmd)

        # get current filename
        active_view = self.window.active_view()
        scope_name = active_view.scope_name(0)

        self.filename = active_view.file_name()
        self.module = self._get_module(self.filename, base=None)

        log(2, "Filename: ", self.filename)
        log(2, "Module: ", self.module)

    def _get_module(self, filename, base):
        """ Convert a filename to a "module" relative to the working path """
        if not filename or not filename.endswith('.py'):
            log(2, 'Cannot get module for non python-source file: ', filename)
            return ''  # only python modules are supported
        base = base or os.path.join(
            self.window.extract_variables().get('project_path', ''),
            self.window.extract_variables().get('project_base_name', ''))
        base = os.path.abspath(base)
        filename = os.path.abspath(filename)
        log(2, 'Getting module for file %s relative to base %s' % (filename, base))
        if not filename.startswith(base):
            log(2, 'Cannot determine module path outside of directory')
            return ''
        return filename.replace(base, '').replace(os.path.sep, '.')[:-3].strip('.')

    def _get_default_kwargs(self, addl_kwargs):
        if 'shell_cmd' in addl_kwargs:
            kwargs = {}
        else:
            kwargs = {
                'cmd': self.default_cmd,
                # trim the following string in-between interpolated parts
                'sep_cleanup': '::',
            }
        if self.is_to_use_ansiescape:
            kwargs['syntax'] = "Packages/ANSIescape/ANSI.tmLanguage"
        return kwargs

    def _format_placeholder(self, cmd, sep, **kwargs):
        result = []
        for part in cmd:
            try:
                part = part.format(**kwargs).strip(sep).strip('.')
                cleaned_part = re.sub('%s+' % sep, sep, part).strip(sep)
                if cleaned_part:
                    result.append(cleaned_part)
            except KeyError:
                # ignore commands with unparsed parts
                continue
        return result

    def get_pattern(self, view, python_exec):
        log(2, "View: ", view)
        pattern = view and utils.get_test(view, use_python=python_exec)
        log(2, 'Test pattern: ', pattern)
        self.class_name, self.func_name = pattern
        log(2, 'self.func_name: %s, self.class_name: %s' % (self.func_name, self.class_name))

        if not self.class_name and not self.func_name:
            old_func_name, old_class_name, old_filename = g_last_function_class_names[self.window_id]

            if not old_func_name and not old_class_name:
                self.class_name = self.func_name = None
                log(2, "Raising NoTestFound()")
                raise NoTestFound()

        if self.run_last_valid_test:
            self.get_last_test()

    def get_last_test(self):
        old_func_name, old_class_name, old_filename = g_last_function_class_names[self.window_id]
        log(2, 'get_last_test func_name %sclass_name %s filename %s' % (self.func_name, self.class_name, self.filename))
        log(2, 'get_last_test old_func_name %s old_class_name %s old_filename %s' % (old_func_name, old_class_name, old_filename))

        if not self.func_name or self.func_name and not self.func_name.lower().startswith( 'test_' ):
            self.func_name = old_func_name
            self.class_name = old_class_name
            self.filename = old_filename

        if self.func_name:
            old_func_name = self.func_name

        if self.class_name:
            old_class_name = self.class_name

        if self.filename:
            old_filename = self.filename

        g_last_function_class_names[self.window_id] = (old_func_name, old_class_name, old_filename)

    def get_command_kwargs(self, **addl_kwargs):
        # prepare default command arguments
        kwargs = deepcopy(self._get_default_kwargs(addl_kwargs))
        extra_args = kwargs.pop('extra_cmd_args', [])
        kwargs.update(addl_kwargs)
        kwargs.get('cmd', []).extend(extra_args)
        if 'shell_cmd' in kwargs: kwargs['shell_cmd'] = kwargs['shell_cmd'] + " ".join(extra_args)

        # get the command environment
        # TODO: infer from settings.python_interpreter and settings.src_root settings
        #       as used in https://github.com/JulianEberius/SublimePythonIDE
        if 'env' not in kwargs:
            kwargs['env'] = {}
        if 'working_dir' in kwargs:
            self.module = self._get_module(self.filename, base=kwargs['working_dir'])
            log(2, "Module updated: ", self.module)
        else:
            kwargs['working_dir'] = ''

        # find the test module/file/pattern in the view
        view = self.window.active_view()

        # use a given python executable to parse the tests (using ast)
        default_python = self.settings.get('python_executable', None)
        python_executable = kwargs.pop('python_executable', None) or default_python
        self.get_pattern(view, python_exec=python_executable)
        log(2, 'func_name %s class_name %s filename %s' % (self.func_name, self.class_name, self.filename))

        fmt_args = dict(
            module=self.module or '',
            filename=self.filename or '',
            test_class=self.class_name or '',
            test_func=self.func_name or '',
        )
        selection = utils.get_selection_content(view)
        if selection:
            fmt_args['selection'] = selection

        log(2, 'kwargs: %s' %(kwargs))
        log(2, 'fmt_args: %s' %(fmt_args))

        sep_cleanup = kwargs.pop('sep_cleanup') if 'sep_cleanup' in kwargs else '::'
        if 'cmd' in kwargs:
            kwargs['cmd'] = self._format_placeholder(
                    kwargs['cmd'], sep_cleanup, **fmt_args)

        if 'shell_cmd' in kwargs:
            kwargs['shell_cmd'] = self._format_placeholder(
                    [kwargs['shell_cmd']], sep_cleanup, **fmt_args)[0]

        # default external command can be used if not given
        if kwargs.get('external', self.external_runner):
            kwargs['external'] = kwargs.get('external', self.external_runner)

        return kwargs

    def get_external_command(self, external, kwargs):
        log(2, 'Running external command (%s)' % external)

        if isinstance(external, bool):
            # if "external": true, use our default
            default = utils.get_default_command()
            base_command = self.settings.get("default_external", default)
        elif isinstance(external, (list, tuple)):
            base_command = external
        else:
            raise Exception("External command must be either true/false"
                            " or a list of arguments")

        _env = ' '.join('%s=%s' % (ename, evalue) for
                        ename, evalue in kwargs['env'].items())
        change_dir_cmd = ''
        if kwargs['working_dir']:
            change_dir_cmd = 'cd {path} && '.format(path=kwargs['working_dir'])
        elif self.filename:
            # for running individual arbitrary test modules
            filename_dir = os.path.dirname(self.filename)
            change_dir_cmd = 'cd {path} && '.format(path=filename_dir)

        _cmd = '{cwd}{env_setup} {cmd}'.format(
            cwd=change_dir_cmd,
            cmd=' '.join(kwargs['cmd']),
            env_setup=_env,
        )
        return (base_command) + [_cmd]

    def setup_ansiescape(self, command_kwargs):
        sublimeansi = 'sublimeansi'

        if sublimeansi in command_kwargs:
            command_kwargs.pop( sublimeansi )
            self.is_to_use_ansiescape = True

        else:
            self.is_to_use_ansiescape = False
        log(2, "is_to_use_ansiescape:", self.is_to_use_ansiescape)

    def _update_kwards(self, new_kwargs, original_kwargs):

        for original, value in original_kwargs.items():

            if original not in ('cmd', 'shell_cmd'):
                new_kwargs[original] = original_kwargs[original]

    def run(self, *args, **command_kwargs):
        log._debugger_level = 3 if utils.DEBUG() else 1
        log(2, 'SublimeTestPlier running in debug mode')
        log(2, "Args: %s" % list(args))
        log(2, "Kwargs: %s" % command_kwargs)

        global g_last_valid_kwargs
        original_kwargs = dict( command_kwargs )
        self.setup_ansiescape( command_kwargs )

        active_view = self.window.active_view()
        scope_name = active_view.scope_name(0)

        if scope_name.startswith( "source.python" ):
            self.setup_runner()

            try:
                new_kwargs = self.get_command_kwargs(**command_kwargs)
                g_last_valid_kwargs = new_kwargs

            except NoTestFound:
                new_kwargs = g_last_valid_kwargs

        else:
            new_kwargs = g_last_valid_kwargs

        self._update_kwards( new_kwargs, original_kwargs )

        log(2, '\n')
        if 'external' in new_kwargs:
            cmd = self.get_external_command(new_kwargs['external'], new_kwargs)
            log(2, 'Running external runner with cmd: %s' % new_kwargs)
            return self.window.run_command("exec", {'cmd': cmd})

        elif self.is_to_use_ansiescape:
            log(2, 'Running internal command (with ANSI colors): %s' % new_kwargs)
            return self.window.run_command("ansi_color_build", new_kwargs)

        else:
            log(2, 'Running internal command (without ANSI colors): %s' % new_kwargs)
            return self.window.run_command("exec", new_kwargs)
