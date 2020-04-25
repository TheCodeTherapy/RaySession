
import os
import subprocess
import sys
from liblo import Address
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtXml  import QDomDocument

import ray

from client import Client
from multi_daemon_file import MultiDaemonFile
from signaler import Signaler
from scripter import Scripter
from daemon_tools import Terminal, CommandLineArgs
from session import OperatingSession

_translate = QCoreApplication.translate
signaler = Signaler.instance()

def session_operation(func):
    def wrapper(*args, **kwargs):
        if len(args) < 4:
            return 
        
        sess, path, osc_args, src_addr, *rest = args
        
        if sess.steps_order:
            sess.send(src_addr, "/error", path, ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            return
        
        if sess.file_copier.isActive():
            if path.startswith('/nsm/server/'):
                sess.send(src_addr, "/error", path, ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            else:
                sess.send(src_addr, "/error", path, ray.Err.COPY_RUNNING, 
                        "ray-daemon is copying files.\n"
                            + "Wait copy finish or abort copy,\n"
                            + "and restart operation !\n")
            return
        
        sess.rememberOscArgs(path, osc_args, src_addr)
        
        response = func(*args)
        sess.nextFunction()
        
        return response
    return wrapper


class SignaledSession(OperatingSession):
    def __init__(self, root):
        OperatingSession.__init__(self, root)
        
        signaler.osc_recv.connect(self.oscReceive)
        #signaler.script_finished.connect(self.scriptFinished)
        signaler.dummy_load_and_template.connect(self.dummyLoadAndTemplate)
        
    def oscReceive(self, path, args, types, src_addr):
        nsm_equivs = {"/nsm/server/add" : "/ray/session/add_executable",
                      "/nsm/server/save": "/ray/session/save",
                      "/nsm/server/open": "/ray/server/open_session",
                      "/nsm/server/new" : "/ray/server/new_session",
                      "/nsm/server/duplicate": "/ray/session/duplicate",
                      "/nsm/server/close": "/ray/session/close",
                      "/nsm/server/abort": "/ray/session/abort",
                      "/nsm/server/quit" : "/ray/server/quit"}
                      # /nsm/server/list is not used here because it doesn't
                      # works as /ray/server/list_sessions
        
        nsm_path = nsm_equivs.get(path)
        func_path = nsm_path if nsm_path else path
        
        func_name = func_path.replace('/', '_')
        
        if func_name in self.__dir__():
            function = self.__getattribute__(func_name)
            client_id = ''
                    
            function(path, args, src_addr)
    
    def sendErrorNoClient(self, src_addr, path, client_id):
        self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                  _translate('GUIMSG', "No client with this client_id:%s")
                    % client_id)
    
    def sendErrorCopyRunning(self, src_addr, path):
        self.send(src_addr, "/error", path, ray.Err.COPY_RUNNING,
                  _translate('GUIMSG', "Impossible, copy running !"))
    
    ############## FUNCTIONS CONNECTED TO SIGNALS FROM OSC ###################
    
    def _nsm_server_announce(self, path, args, src_addr):
        client_name, capabilities, executable_path, major, minor, pid = args
        
        if self.wait_for == ray.WaitFor.QUIT:
            if path.startswith('/nsm/server/'):
                # Error is wrong but compatible with NSM API
                self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN, 
                          "Sorry, but there's no session open "
                          + "for this application to join.")
            return
        
        #we can't be absolutely sure that the announcer is the good one
        #but if client announce a known PID, 
        #we can be sure of which client is announcing
        for client in self.clients: 
            if client.pid == pid and not client.active and client.isRunning():
                client.serverAnnounce(path, args, src_addr, False)
                break
        else:
            for client in self.clients:
                if (not client.active and client.isRunning()
                    and ray.isPidChildOf(pid, client.pid)):
                        client.serverAnnounce(path, args, src_addr, False)
                        break
            else:
                # Client launched externally from daemon
                # by command : $:NSM_URL=url executable
                client = self.newClient(executable_path)
                self.externals_timer.start()
                client.serverAnnounce(path, args, src_addr, True)
            
            #n = 0
            #for client in self.clients:
                #if (os.path.basename(client.executable_path) \
                        #== os.path.basename(executable_path)
                    #and not client.active
                    #and client.pending_command == ray.Command.START):
                        #n+=1
                        #if n>1:
                            #break
                        
            #if n == 0:
                ## Client launched externally from daemon
                ## by command : $:NSM_URL=url executable
                #client = self.newClient(args[2])
                #client.is_external = True
                #self.externals_timer.start()
                #client.serverAnnounce(path, args, src_addr, True)
                #return
                
            #elif n == 1:
                #for client in self.clients:
                    #if (os.path.basename(client.executable_path) \
                            #== os.path.basename(executable_path)
                        #and not client.active
                        #and client.pending_command == ray.Command.START):
                            #client.serverAnnounce(path, args, src_addr, False)
                            #break
            #else:
                #for client in self.clients:
                    #if (not client.active
                        #and client.pending_command == ray.Command.START):
                            #if ray.isPidChildOf(pid, client.pid):
                                #client.serverAnnounce(path, args, 
                                                      #src_addr, False)
                                #break
        
        if self.wait_for == ray.WaitFor.ANNOUNCE:
            self.endTimerIfLastExpected(client)
    
    def _reply(self, path, args, src_addr):
        if self.wait_for == ray.WaitFor.QUIT:
            return
        
        message = args[1]
        client = self.getClientByAddress(src_addr)
        if client:
            client.setReply(ray.Err.OK, message)
            
            server = self.getServer()
            if (server 
                    and server.getServerStatus() == ray.ServerStatus.READY
                    and server.option_desktops_memory):
                self.desktops_memory.replace()
        else:
            self.message("Reply from unknown client")
    
    def _error(self, path, args, src_addr):
        path, errcode, message = args
        
        client = self.getClientByAddress(src_addr)
        if client:
            client.setReply(errcode, message)
            
            if self.wait_for == ray.WaitFor.REPLY:
                self.endTimerIfLastExpected(client)
        else:
            self.message("error from unknown client")
    
    def _nsm_client_label(self, path, args, src_addr):
        client = self.getClientByAddress(src_addr)
        if client:
            client.setLabel(args[0])
    
    def _nsm_client_network_properties(self, path, args, src_addr):
        client = self.getClientByAddress(src_addr)
        if client:
            net_daemon_url, net_session_root = args
            client.setNetworkProperties(net_daemon_url, net_session_root)
    
    def _nsm_client_no_save_level(self, path, args, src_addr):
        client = self.getClientByAddress(src_addr)
        if client and client.isCapableOf(':warning-no-save:'):
            client.no_save_level = args[0]
            
            self.sendGui('/ray/gui/client/no_save_level',
                         client.client_id, client.no_save_level)
    
    def _ray_server_abort_copy(self, path, args, src_addr):
        self.file_copier.abort()
    
    def _ray_server_abort_snapshot(self, path, args, src_addr):
        self.snapshoter.abort()
    
    def _ray_server_change_root(self, path, args, src_addr):
        session_root = args[0]
        if self.path:
            self.send(src_addr, '/error', path, ray.Err.SESSION_LOCKED,
                      "impossible to change root. session %s is loaded"
                        % self.path)
            return
        
        if not os.path.exists(session_root):
            try:
                os.makedirs(session_root)
            except:
                self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                          "invalid session root !")
                return
        
        if not os.access(session_root, os.W_OK):
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      "unwriteable session root !")
            return
        
        self.root = session_root
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()
            
        self.send(src_addr, '/reply', path, 
                  "root folder changed to %s" % self.root)
        self.sendGui('/ray/gui/server/root', self.root)
    
    def _ray_server_list_sessions(self, path, args, src_addr):
        with_net = False
        if args:
            with_net = args[0]
        
        if with_net:
            for client in self.clients:
                if client.net_daemon_url:
                    self.send(Address(client.net_daemon_url), 
                              '/ray/server/list_sessions', 1)
        
        if not self.root:
            return
        
        session_list = []
        
        for root, dirs, files in os.walk(self.root):
            #exclude hidden files and dirs
            files   = [f for f in files if not f.startswith('.')]
            dirs[:] = [d for d in dirs  if not d.startswith('.')]
            
            if root == self.root:
                continue
            
            already_sent = False
            
            for file in files:
                if file in ('raysession.xml', 'session.nsm'):
                    if not already_sent:
                        basefolder = root.replace(self.root + '/', '', 1)
                        session_list.append(basefolder)
                        if len(session_list) == 20:
                            self.send(src_addr, "/reply", path,
                                      *session_list)
                            
                            session_list.clear()
                        already_sent = True
                    
        if session_list:
            self.send(src_addr, "/reply", path, *session_list)
            
        self.send(src_addr, "/reply", path)
    
    def _nsm_server_list(self, path, args, src_addr):
        session_list = []
        
        if self.root:
            for root, dirs, files in os.walk(self.root):
                #exclude hidden files and dirs
                files   = [f for f in files if not f.startswith('.')]
                dirs[:] = [d for d in dirs  if not d.startswith('.')]
                
                if root == self.root:
                    continue
                
                for file in files:
                    if file in ('raysession.xml', 'session.nsm'):
                        basefolder = root.replace(self.root + '/', '', 1)
                        self.send(src_addr, '/reply', '/nsm/server/list',
                                basefolder)
                        
        self.send(src_addr, path, ray.Err.OK, "Done.")
    
    @session_operation
    def _ray_server_new_session(self, path, args, src_addr):
        if len(args) == 2 and args[1]:
            session_name, template_name = args
            
            spath = ''
            if session_name.startswith('/'):
                spath = session_name
            else:
                spath = "%s/%s" % (self.root, session_name)
            
            if not os.path.exists(spath):
                self.steps_order = [self.save,
                                      self.closeNoSaveClients,
                                      self.snapshot,
                                      (self.prepareTemplate, *args, False),
                                      (self.preload, session_name),
                                       self.takePlace,
                                       self.load,
                                       self.newDone]
                return
        
        self.steps_order = [self.save,
                              self.closeNoSaveClients,
                              self.snapshot,
                              self.close,
                              (self.new, args[0]),
                              self.save,
                              self.newDone]
    
    @session_operation
    def _ray_server_open_session(self, path, args, src_addr, open_off=False):
        session_name = args[0]
        save_previous = True
        template_name = ''
        
        if len(args) >= 2:
            save_previous = bool(args[1])
        if len(args) >= 3:
            template_name = args[2]
            
        if (not session_name
                or '//' in session_name
                or session_name.startswith(('../', '.ray-', 'ray-'))):
            self.sendError(ray.Err.CREATE_FAILED, 'invalid session name.')
            return
        
        if template_name:
            if '/' in template_name:
                self.sendError(ray.Err.CREATE_FAILED, 'invalid template name')
                return
            
        spath = ''
        if session_name.startswith('/'):
            spath = session_name
        else:
            spath = "%s/%s" % (self.root, session_name)
        
        if spath == self.path:
            self.sendError(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG', 'session %s is already opened !')
                    % ray.highlightText(session_name))
            return
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if (multi_daemon_file
                and not multi_daemon_file.isFreeForSession(spath)):
            Terminal.warning("Session %s is used by another daemon"
                              % ray.highlightText(spath))
            
            self.sendError(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG', 
                    'session %s is already used by another daemon !')
                        % ray.highlightText(session_name))
            return
        
        # don't use template if session folder already exists
        if os.path.exists(spath):
            template_name = ''
        
        self.steps_order = []
        
        if save_previous:
            self.steps_order += [(self.save, True)]
        
        self.steps_order += [self.closeNoSaveClients]
        
        if save_previous:
            self.steps_order += [(self.snapshot, '', '', False, True)]
        
        if template_name:
            self.steps_order += [(self.prepareTemplate, session_name, 
                                    template_name, True)]
        
        self.steps_order += [(self.preload, session_name),
                             (self.close, open_off),
                             self.takePlace,
                             (self.load, open_off),
                             self.loadDone]
    
    def _ray_server_open_session_off(self, path, args, src_addr):
        self._ray_server_open_session(path, args, src_addr, True)
    
    def _ray_server_rename_session(self, path, args, src_addr):
        tmp_session = DummySession(self.root)
        tmp_session.ray_server_rename_session(path, args, src_addr)
    
    @session_operation
    def _ray_session_save(self, path, args, src_addr):
        self.steps_order = [self.save, self.snapshot, self.saveDone]
    
    @session_operation
    def _ray_session_save_as_template(self, path, args, src_addr):
        template_name = args[0]
        net = False if len(args) < 2 else args[1]
        
        for client in self.clients:
            if client.executable_path == 'ray-network':
                client.net_session_template = template_name
        
        self.steps_order = [self.save, self.snapshot,
                              (self.saveSessionTemplate, 
                               template_name, net)]
                              
    def _ray_server_save_session_template(self, path, args, src_addr):
        if len(args) == 2:
            session_name, template_name = args
            sess_root = self.root
            net=False
        else:
            session_name, template_name, sess_root = args
            net=True
        
        tmp_session = DummySession(sess_root)
        tmp_session.ray_server_save_session_template(path, 
                                [session_name, template_name, net], 
                                src_addr)
        
        #if (sess_root != self.root or session_name != self.name):
            #tmp_session = DummySession(sess_root)
            #tmp_session.ray_server_save_session_template(path, 
                                #[session_name, template_name, net], 
                                #src_addr)
            #return
        
        #self.ray_session_save_as_template(path, [template_name, net],
                                          #src_addr)
                                          
                                          
        #if net:
            #for client in self.clients:
                #if client.executable_path == 'ray-network':
                    #client.net_session_template = template_name
        
        #self.rememberOscArgs()
        #self.steps_order = [self.save, self.snapshot,
                              #(self.saveSessionTemplate, template_name, net)]
        #self.nextFunction()
    
    @session_operation
    def _ray_session_take_snapshot(self, path, args, src_addr):
        snapshot_name, with_save = args
            
        self.steps_order.clear()
        
        if with_save:
            self.steps_order.append(self.save)
        self.steps_order += [(self.snapshot, snapshot_name, '', True),
                               self.snapshotDone]
    
    @session_operation
    def _ray_session_close(self, path, args, src_addr):
        self.steps_order = [(self.save, True),
                              self.closeNoSaveClients,
                              self.snapshot,
                              (self.close, True),
                              self.closeDone]
    
    def _ray_session_abort(self, path, args, src_addr):
        if not self.path:
            self.file_copier.abort()
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to abort." )
            return
        
        self.wait_for = ray.WaitFor.NONE
        self.timer.stop()
        
        # Non Session Manager can't abort if an operation pending
        # RS can and it would be a big regression to remove this feature
        # So before to abort we need to send an error reply
        # to the last server control message
        # if an operation pending.
        
        if self.steps_order:
            if self.osc_path.startswith('/nsm/server/'):
                short_path = self.osc_path.rpartition('/')[2]
                
                if short_path == 'save':
                    self.saveError(ray.Err.CREATE_FAILED)
                elif short_path == 'open':
                    self.loadError(ray.Err.SESSION_LOCKED)
                elif short_path == 'new':
                    self.sendError(ray.Err.CREATE_FAILED, 
                                "Could not create the session directory")
                elif short_path == 'duplicate':
                    self.duplicateAborted(self.osc_args[0])
                elif short_path in ('close', 'abort', 'quit'):
                    # let the current close works here
                    self.send(src_addr, "/error", path, 
                              ray.Err.OPERATION_PENDING,
                              "An operation pending.")
                    return
            else:
                self.sendError(ray.Err.ABORT_ORDERED, 
                               _translate('GUIMSG',
                                    'abort ordered from elsewhere, sorry !'))
        
        self.rememberOscArgs(path, args, src_addr)
        self.steps_order = [(self.close, True), self.abortDone]
        
        if self.file_copier.isActive():
            self.file_copier.abort(self.nextFunction, [])
        else:
            self.nextFunction()
    
    def _ray_server_quit(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        self.steps_order = [self.terminateStepScripter,
                            self.close, self.exitNow]
        
        if self.file_copier.isActive():
            self.file_copier.abort(self.nextFunction, [])
        else:
            self.nextFunction()
    
    def _ray_session_cancel_close(self, path, args, src_addr):
        if not self.steps_order:
            return 
        
        self.timer.stop()
        self.timer_waituser_progress.stop()
        self.steps_order.clear()
        self.cleanExpected()
        self.setServerStatus(ray.ServerStatus.READY)
        
    def _ray_session_skip_wait_user(self, path, args, src_addr):
        if not self.steps_order:
            return 
        
        self.timer.stop()
        self.timer_waituser_progress.stop()
        self.cleanExpected()
        self.nextFunction()
    
    @session_operation
    def _ray_session_duplicate(self, path, args, src_addr):
        new_session_full_name = args[0]
        
        spath = ''
        if new_session_full_name.startswith('/'):
            spath = new_session_full_name
        else:
            spath = "%s/%s" % (self.root, new_session_full_name)
        
        if os.path.exists(spath):
            self.sendError(ray.Err.CREATE_FAILED, 
                _translate('GUIMSG', "%s already exists !")
                    % ray.highlightText(spath))
            return
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if (multi_daemon_file
                and not multi_daemon_file.isFreeForSession(spath)):
            Terminal.warning("Session %s is used by another daemon"
                             % ray.highlightText(new_session_full_name))
            self.sendError(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG', 
                    'session %s is already used by this or another daemon !')
                        % ray.highlightText(new_session_full_name))
            return
        
        self.steps_order = [self.save,
                              self.closeNoSaveClients,
                              self.snapshot,
                              (self.duplicate, new_session_full_name),
                              (self.preload, new_session_full_name),
                              self.close,
                              self.takePlace,
                              self.load, 
                              self.duplicateDone]
        
    def _ray_session_duplicate_only(self, path, args, src_addr):
        session_to_load, new_session, sess_root = args
        
        spath = ''
        if new_session.startswith('/'):
            spath = new_session
        else:
            spath = "%s/%s" % (sess_root, new_session)
        
        if os.path.exists(spath):
            self.send(src_addr, '/ray/net_daemon/duplicate_state', 1)
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED, 
                      _translate('GUIMSG', "%s already exists !")
                        % ray.highlightText(spath))
            return
        
        if sess_root == self.root and session_to_load == self.getShortPath():
            if (self.steps_order
                or self.file_copier.isActive()):
                    self.send(src_addr, '/ray/net_daemon/duplicate_state', 1)
                    return
            
            self.rememberOscArgs(path, args, src_addr)
            
            self.steps_order = [self.save,
                                  self.snapshot,
                                  (self.duplicate, new_session),
                                  self.duplicateOnlyDone]
            
            self.nextFunction()
        
        else:
            tmp_session = DummySession(sess_root)
            tmp_session.osc_src_addr = src_addr
            tmp_session.dummyDuplicate(session_to_load, new_session)
    
    @session_operation
    def _ray_session_open_snapshot(self, path, args, src_addr):
        if not self.path:
            return 
        
        snapshot = args[0]
        
        self.steps_order = [self.save,
                              self.closeNoSaveClients,
                              (self.snapshot, '', snapshot, True),
                              (self.close, True),
                              (self.initSnapshot, self.path, snapshot),
                              (self.preload, self.path),
                              self.takePlace,
                              self.load,
                              self.loadDone]
    
    def _ray_session_rename(self, path, args, src_addr):
        new_session_name = args[0]
        
        if self.steps_order:
            return
        
        if not self.path:
            return
        
        if self.file_copier.isActive():
            return
        
        if new_session_name == self.name:
            return
        
        if not self.isNsmLocked():
            for filename in os.listdir(os.path.dirname(self.path)):
                if filename == new_session_name:
                    # another directory exists with new session name
                    return
        
        for client in self.clients:
            if client.isRunning():
                self.sendGuiMessage(
                    _translate('GUIMSG', 
                               'Stop all clients before rename session !'))
                return
        
        for client in self.clients + self.trashed_clients:
            client.adjustFilesAfterCopy(new_session_name, ray.Template.RENAME)
        
        if not self.isNsmLocked():
            try:
                spath = "%s/%s" % (os.path.dirname(self.path), new_session_name)
                subprocess.run(['mv', self.path, spath])
                self.setPath(spath)
                
                self.sendGuiMessage(
                    _translate('GUIMSG', 'Session directory is now: %s')
                    % self.path)
            except:
                pass
        
        self.sendGuiMessage(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (self.name, new_session_name))
        self.sendGui('/ray/gui/session/name', self.name, self.path)
    
    def _ray_session_add_executable(self, path, args, src_addr):
        executable = args[0]
        via_proxy = 0
        prefix_mode = ray.PrefixMode.SESSION_NAME
        custom_prefix = ''
        client_id = ""
        start_it = True
        
        if len(args) == 2 and args[1] == 'not_auto_start':
            start_it = False
        
        if len(args) == 5:
            executable, via_proxy, prefix_mode, custom_prefix, client_id = args
            
            if prefix_mode == ray.PrefixMode.CUSTOM and not custom_prefix:
                prefix_mode = ray.PrefixMode.SESSION_NAME
            
            if client_id:
                if not client_id.replace('_', '').isalnum():
                    self.sendError(ray.Err.CREATE_FAILED,
                            _translate("error", "client_id %s is not alphanumeric")
                                % client_id )
                    return
                
                # Check if client_id already exists
                for client in self.clients + self.trashed_clients:
                    if client.client_id == client_id:
                        self.sendError(ray.Err.CREATE_FAILED,
                            _translate("error", "client_id %s is already used")
                                % client_id )
                        return
        
        if not client_id:
            client_id = self.generateClientId(executable)
            
        client = Client(self)
        
        if via_proxy:
            client.executable_path = 'ray-proxy'
            client.tmp_arguments = "--executable %s" % executable
        else:
            client.executable_path = executable
        
        client.name = os.path.basename(executable)
        client.client_id = client_id
        client.prefix_mode = prefix_mode
        client.custom_prefix = custom_prefix
        client.icon = client.name.lower().replace('_', '-')
        client.setDefaultGitIgnored(executable)
        
        if self.addClient(client):
            if start_it:
                client.start()
            self.send(src_addr, '/reply', path, client.client_id)
        else:
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                      "Impossible to add client now")
    
    def _ray_session_add_proxy(self, path, args, src_addr):
        executable = args[0]
        
        client = Client(self)
        client.executable_path = 'ray-proxy'
        
        client.tmp_arguments  = "--executable %s" % executable
        if CommandLineArgs.debug:
            client.tmp_arguments += " --debug"
            
        client.name = os.path.basename(executable)
        client.client_id = self.generateClientId(client.name)
        client.icon = client.name.lower().replace('_', '-')
        client.setDefaultGitIgnored(executable)
        
        if self.addClient(client):
            client.start()
            self.send(src_addr, '/reply', path, client.client_id)
        else:
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                      "Impossible to add client now")
    
    def _ray_session_add_client_template(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        factory = bool(args[0])
        template_name = args[1]
        
        self.addClientTemplate(src_addr, path, template_name, factory)
    
    def _ray_session_add_factory_client_template(self, path, args, src_addr):
        self._ray_session_add_client_template(path, [1, args[0]], src_addr)
    
    def _ray_session_add_user_client_template(self, path, args, src_addr):
        self._ray_session_add_client_template(path, [0, args[0]], src_addr)
    
    def _ray_session_reorder_clients(self, path, args, src_addr):
        client_ids_list = args
        
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "no session to reorder clients")
        
        if len(self.clients) < 2:
            self.send(src_addr, '/reply', path, "clients reordered")
            return
        
        self.reOrderClients(client_ids_list, src_addr, path)
    
    def _ray_session_clear_clients(self, path, args, src_addr):
        if not self.load_locked:
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                "clear_clients has to be used only during the load script !")
            return
        
        self.clearClients(src_addr, path, *args)
    
    def _ray_session_list_snapshots(self, path, args, src_addr, client_id=""):
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "no session to list snapshots")
            return
        
        auto_snapshot = not bool(
            self.snapshoter.isAutoSnapshotPrevented())
        self.sendGui('/ray/gui/session/auto_snapshot',  int(auto_snapshot))
        
        snapshots = self.snapshoter.list(client_id)
        
        i=0
        snap_send = []
        
        for snapshot in snapshots:
            if i == 20:
                self.send(src_addr, '/reply', path, *snap_send)
                
                snap_send.clear()
                i=0
            else:
                snap_send.append(snapshot)
                i+=1
        
        if snap_send:
            self.send(src_addr, '/reply', path, *snap_send)
        self.send(src_addr, '/reply', path)
        
    def _ray_session_set_auto_snapshot(self, path, args, src_addr):
        self.snapshoter.setAutoSnapshot(bool(args[0]))
    
    def _ray_session_list_clients(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      _translate('GUIMSG', 'No session to list clients !'))
            return 
        
        f_started = -1
        f_active = -1
        f_auto_start = -1
        f_no_save_level = -1
        
        search_properties = []
        
        for arg in args:
            cape = 1
            if arg.startswith('not_'):
                cape = 0
                arg = arg.replace('not_', '', 1)
            
            if ':' in arg:
              search_properties.append((cape, arg))
            
            elif arg == 'started':
                f_started = cape
            elif arg == 'active':
                f_active = cape
            elif arg == 'auto_start':
                f_auto_start = cape
            elif arg == 'no_save_level':
                f_no_save_level = cape
                
        client_id_list = []
        
        for client in self.clients:
            if ((f_started < 0 or f_started == client.isRunning())
                and (f_active < 0 or f_active == client.active)
                and (f_auto_start < 0 or f_auto_start == client.auto_start)
                and (f_no_save_level < 0 
                     or f_no_save_level == int(bool(client.no_save_level)))):
                if search_properties:
                    message = client.getPropertiesMessage()
                    
                    for cape, search_prop in search_properties:
                        line_found = False
                        
                        for line in message.split('\n'):
                            if line == search_prop:
                                line_found = True
                                break
                            
                        if cape != line_found:
                            break
                    else:
                        client_id_list.append(client.client_id)
                else:
                    client_id_list.append(client.client_id)
                    
        if client_id_list:
            self.send(src_addr, '/reply', path, *client_id_list)
        self.send(src_addr, '/reply', path)
    
    def _ray_session_list_trashed_clients(self, path, args, src_addr):
        client_id_list = []
        
        for trashed_client in self.trashed_clients:
            client_id_list.append(trashed_client.client_id)
            
        if client_id_list:
            self.send(src_addr, '/reply', path, *client_id_list)
        self.send(src_addr, '/reply', path)
    
    def _ray_session_run_step(self, path, args, src_addr):
        if not self.step_scripter.isRunning():
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
              'No stepper script running, run run_step from session scripts')
            return 
        
        if self.step_scripter.stepperHasCalled():
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
             'step already done. Run run_step only one time in the script')
            return
        
        if not self.steps_order:
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                      'No operation pending !')
            return
        
        self.run_step_addr = src_addr
        self.nextFunction(True, args)
    
    def _ray_client_stop(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client.stop(src_addr, path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_kill(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client.kill()
                self.send(src_addr, "/reply", path, "Client killed." )
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_trash(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    self.send(src_addr, '/error', path, ray.Err.OPERATION_PENDING,
                              "Stop client before to trash it !")
                    return
                
                if self.file_copier.isActive(client_id):
                    self.file_copier.abort()
                    self.send(src_addr, '/error', path, ray.Err.COPY_RUNNING,
                              "Files were copying for this client.")
                    return
                
                self.trashClient(client)
                
                self.send(src_addr, "/reply", path, "Client removed.")
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_start(self, path, args, src_addr):
        self._ray_client_resume(path, args, src_addr)
    
    def _ray_client_resume(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    self.sendGuiMessage(
                        _translate('GUIMSG', 'client %s is already running.')
                            % client.guiMsgStyle())
                    
                    # make ray_control exit code 0 in this case
                    self.send(src_addr, '/reply', path, 'client running')
                    return
                    
                if self.file_copier.isActive(client.client_id):
                    self.sendErrorCopyRunning(src_addr, path)
                    return
                
                client.start(src_addr, path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_open(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if self.file_copier.isActive(client.client_id):
                    self.sendErrorCopyRunning(src_addr, path)
                    return
                
                if client.active:
                    self.sendGuiMessage(
                        _translate('GUIMSG', 'client %s is already active.')
                            % client.guiMsgStyle())
                    
                    # make ray_control exit code 0 in this case
                    self.send(src_addr, '/reply', path, 'client active')
                else:
                    client.load(src_addr, path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_save(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.active and not client.no_save_level:
                    if self.file_copier.isActive(client.client_id):
                        self.sendErrorCopyRunning(src_addr, path)
                        return
                    client.save(src_addr, path)
                else:
                    self.sendGuiMessage(_translate('GUIMSG',
                                                   "%s is not saveable.")
                                            % client.guiMsgStyle())
                    self.send(src_addr, '/reply', path, 'client saved')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_save_as_template(self, path, args, src_addr):
        client_id, template_name = args
        
        if self.file_copier.isActive():
            self.sendErrorCopyRunning(src_addr, path)
            return
        
        for client in self.clients:
            if client.client_id == client_id:
                client.saveAsTemplate(template_name, src_addr, path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_show_optional_gui(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client.sendToSelfAddress("/nsm/client/show_optional_gui")
                self.send(src_addr, '/reply', path, 'show optional GUI asked')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_hide_optional_gui(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client.sendToSelfAddress("/nsm/client/hide_optional_gui")
                self.send(src_addr, '/reply', path, 'hide optional GUI asked')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_update_properties(self, path, args, src_addr):
        client_data = ray.ClientData(*args)
        
        for client in self.clients:
            if client.client_id == client_data.client_id:
                client.updateClientProperties(client_data)
                self.send(src_addr, '/reply', path,
                          'client properties updated')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_data.client_id)
    
    def _ray_client_set_properties(self, path, args, src_addr):
        client_id = args.pop(0)
        
        message = ''
        
        for arg in args:
            message+="%s\n" % arg
        
        for client in self.clients:
            if client.client_id == client_id:
                client.setPropertiesFromMessage(message)
                self.send(src_addr, '/reply', path,
                          'client properties updated')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_get_properties(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                message = client.getPropertiesMessage()
                self.send(src_addr, '/reply', path, message)
                self.send(src_addr, '/reply', path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_get_proxy_properties(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                proxy_file = '%s/ray-proxy.xml' % client.getProjectPath()
                
                if not os.path.isfile(proxy_file):
                    self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                        _translate('GUIMSG',
                                   '%s seems to not be a proxy client !')
                            % client.guiMsgStyle())
                    return
                
                try:
                    file = open(proxy_file, 'r')
                    xml = QDomDocument()
                    xml.setContent(file.read())
                    content = xml.documentElement()
                    file.close()
                except:
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "impossible to read %s correctly !")
                            % proxy_file)
                    return
                    
                if content.tagName() != "RAY-PROXY":
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "impossible to read %s correctly !")
                            % proxy_file)
                    return
                    
                cte = content.toElement()
                message = ""
                for property in ('executable', 'arguments', 'config_file',
                                    'save_signal', 'stop_signal',
                                    'no_save_level', 'wait_window',
                                    'VERSION'):
                    message += "%s:%s\n" % (property, cte.attribute(property))
                
                # remove last empty line
                message = message.rpartition('\n')[0]
                
                self.send(src_addr, '/reply', path, message)
                self.send(src_addr, '/reply', path)
                    
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_set_proxy_properties(self, path, args, src_addr):
        client_id = args.pop(0)
        
        message=''
        for arg in args:
            message+= "%s\n" % arg
            
        for client in self.clients:
            if client.client_id == client_id:
                proxy_file = '%s/ray-proxy.xml' % client.getProjectPath()
                
                if not os.path.isfile(proxy_file):
                    self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                        _translate('GUIMSG',
                                   '%s seems to not be a proxy client !')
                            % client.guiMsgStyle())
                    return
                
                try:
                    file = open(proxy_file, 'r')
                    xml = QDomDocument()
                    xml.setContent(file.read())
                    content = xml.documentElement()
                    file.close()
                except:
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "impossible to read %s correctly !")
                            % proxy_file)
                    return
                    
                if content.tagName() != "RAY-PROXY":
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "impossible to read %s correctly !")
                            % proxy_file)
                    return
                    
                cte = content.toElement()
                
                for line in message.split('\n'):
                    property, colon, value = line.partition(':')
                    if property in ('executable', 'arguments', 
                            'config_file', 'save_signal', 'stop_signal',
                            'no_save_level', 'wait_window', 'VERSION'):
                        cte.setAttribute(property, value)
                
                try:
                    file = open(proxy_file, 'w')
                    file.write(xml.toString())
                    file.close()
                except:
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "%s is not writeable")
                            % proxy_file)
                    return
                
                self.send(src_addr, '/reply', path, message)
                self.send(src_addr, '/reply', path)
                    
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_list_files(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client_files = client.getProjectFiles()
                self.send(src_addr, '/reply', path, *client_files)
                self.send(src_addr, '/reply', path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_list_snapshots(self, path, args, src_addr):
        self._ray_session_list_snapshots(path, [], src_addr, args[0])
    
    @session_operation
    def _ray_client_open_snapshot(self, path, args, src_addr):
        client_id, snapshot = args
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    self.steps_order = [
                        self.save,
                        (self.snapshot, '', snapshot, True),
                        (self.closeClient, client),
                        (self.loadClientSnapshot, client_id, snapshot),
                        (self.startClient, client)]
                else:
                    self.steps_order = [
                        self.save,
                        (self.snapshot, '', snapshot, True),
                        (self.loadClientSnapshot, client_id, snapshot)]
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_is_started(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    self.send(src_addr, '/reply', path, 'client running')
                else:
                    self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                              _translate('GUIMSG', '%s is not running.')
                                % client.guiMsgStyle())
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_trashed_client_restore(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        for client in self.trashed_clients:
            if client.client_id == args[0]:
                if self.restoreClient(client):
                    self.send(src_addr, '/reply', path, "client restored")
                else:
                    self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                              "Session is in a loading locked state")
                break
        else:
            self.send(src_addr, "/error", path, -10, "No such client.")
    
    def _ray_trashed_client_remove_definitely(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        for client in self.trashed_clients:
            if client.client_id == args[0]:
                break
        else:
            self.send(src_addr, "/error", path, -10, "No such client.")
            return
        
        self.sendGui('/ray/gui/trash/remove', client.client_id)
        
        for file in client.getProjectFiles():
            try:
                subprocess.run(['rm', '-R', file])
            except:
                self.send(src_addr, '/minor_error', path,  -10, 
                          "Error while removing client file %s" % file)
                continue
            
        self.trashed_clients.remove(client)
        
        self.send(src_addr, '/reply', path, "client definitely removed") 
    
    def _ray_net_daemon_duplicate_state(self, path, args, src_addr):
        state = args[0]
        for client in self.clients:
            if (client.net_daemon_url
                and ray.areSameOscPort(client.net_daemon_url, src_addr.url)):
                    client.net_duplicate_state = state
                    client.net_daemon_copy_timer.stop()
                    break
        else:
            return
        
        if state == 1:
            if self.wait_for == ray.WaitFor.DUPLICATE_FINISH:
                self.endTimerIfLastExpected(client)
            return
        
        if (self.wait_for == ray.WaitFor.DUPLICATE_START and state == 0):
            self.endTimerIfLastExpected(client)
            
        client.net_daemon_copy_timer.start()
    
    def _ray_option_bookmark_session_folder(self, path, args, src_addr):
        if self.path:
            if args[0]:
                self.bookmarker.makeAll(self.path)
            else:
                self.bookmarker.removeAll(self.path)
    
    def serverOpenSessionAtStart(self, session_name):
        self.steps_order = [(self.preload, session_name),
                            self.takePlace,
                            self.load,
                            self.loadDone]
        self.nextFunction()
    
    def dummyLoadAndTemplate(self, session_name, template_name, sess_root):
        tmp_session = DummySession(sess_root)
        tmp_session.dummyLoadAndTemplate(session_name, template_name)
    
    def terminate(self):
        if self.terminated_yet:
            return
        
        if self.file_copier.isActive():
            self.file_copier.abort()
        
        self.terminated_yet = True
        self.steps_order = [self.terminateStepScripter,
                            self.close, self.exitNow]
        self.nextFunction()
        

class DummySession(OperatingSession):
    def __init__(self, root):
        OperatingSession.__init__(self, root)
        self.is_dummy = True
        
    def dummyLoadAndTemplate(self, session_full_name, template_name):
        self.steps_order = [(self.preload, session_full_name),
                            self.takePlace,
                            self.load,
                            (self.saveSessionTemplate, template_name, True)]
        self.nextFunction()
        
    def dummyDuplicate(self, session_to_load, new_session_full_name):
        self.steps_order = [(self.preload, session_to_load),
                            self.takePlace,
                            self.load,
                            (self.duplicate, new_session_full_name),
                            self.duplicateOnlyDone]
        self.nextFunction()
        
    def ray_server_save_session_template(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        session_name, template_name, net = args
        self.steps_order = [(self.preload, session_name),
                            self.takePlace,
                            self.load,
                            (self.saveSessionTemplate, template_name, net)]
        self.nextFunction()
        
    def ray_server_rename_session(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        full_session_name, new_session_name = args
        
        self.steps_order = [(self.preload, full_session_name),
                            self.takePlace,
                            self.load,
                            (self.rename, new_session_name),
                            self.save,
                            (self.renameDone, new_session_name)]
        self.nextFunction()
        
        
