# TODO Add guid and sample name to logging output for each sample

from __future__ import division
from ConfigParser import ConfigParser
import os
import datetime
import sys
import re
import __main__
import logging, logging.handlers
import json
import pprint
import copy
from eventgensamples import Sample
from eventgentoken import Token
import urllib
import types
from eventgencounter import Counter
from eventgenqueue import Queue
try:
    import zmq
except ImportError:
    pass
import threading, multiprocessing


# 6/7/14 CS   Adding a new logger adapter class which we will use to override the formatting
#             for all messsages to include the sample they came from
class EventgenAdapter(logging.LoggerAdapter):
    """
    Pass in a sample parameter and prepend sample to all logs
    """
    def process(self, msg, kwargs):
        return "module='%s' sample='%s': %s" % (self.extra['module'], self.extra['sample'], msg), kwargs

    def debugv(self, msg, *args, **kwargs):
        """
        Delegate a debug call to the underlying logger, after adding
        contextual information from this adapter instance.
        """
        msg, kwargs = self.process(msg, kwargs)
        self.logger.debugv(msg, *args, **kwargs)


# 4/21/14 CS  Adding a defined constant whether we're running in standalone mode or not
#             Standalone mode is when we know we're Splunk embedded but we want to force
#             configs to be read from a file instead of via Splunk's REST endpoint.
#             This is used in the OIDemo and others for embedding the eventgen into an 
#             application.  We want to ensure we're reading from files.  It is the app's
#             responsibility to ensure eventgen.conf settings are not exported to where
#             SA-Eventgen can see them.
#              
#             The reason this is a constant instead of a config setting is we must know
#             this before we read any config and we cannot use a command line parameter
#             because we interpret all those as config overrides.

STANDALONE = False



# 5/10/12 CS Some people consider Singleton to be lazy.  Dunno, I like it for convenience.
# My general thought on that sort of stuff is if you don't like it, reimplement it.  I'll consider
# your patch.
class Config:
    """Reads configuration from files or Splunk REST endpoint and stores them in a 'Borg' global.
    Borg is a variation on the Singleton design pattern which allows us to continually instantiate
    the configuration object throughout the application and maintain state."""
    # Stolen from http://code.activestate.com/recipes/66531/
    # This implements a Borg patterns, similar to Singleton
    # It allows numerous instantiations but always shared state
    __sharedState = {}

    # Internal vars
    _firsttime = True
    _confDict = None

    # Externally used vars
    debug = False
    verbose = False
    splunkEmbedded = False
    sessionKey = None
    grandparentdir = None
    greatgrandparentdir = None
    samples = [ ]
    sampleDir = None
    outputWorkers = None
    generatorWorkers = None
    sampleTimers = [ ]
    workers = [ ]

    # Config file options.  We do not define defaults here, rather we pull them in
    # from eventgen.conf.
    # These are only options which are valid in the 'global' stanza
    # 5/22 CS Except for blacklist, we define that in code, since splunk complains about it in
    # the config files
    disabled = None
    blacklist = ".*\.part"
    spoolDir = None
    spoolFile = None
    breaker = None
    sampletype = None
    interval = None
    delay = None
    count = None
    bundlelines = None
    earliest = None
    latest = None
    hourOfDayRate = None
    dayOfWeekRate = None
    randomizeCount = None
    randomizeEvents = None
    outputMode = None
    fileName = None
    fileMaxBytes = None
    fileBackupFiles = None
    splunkHost = None
    splunkPort = None
    splunkMethod = None
    index = None
    source = None
    host = None
    hostRegex = None
    sourcetype = None
    projectID = None
    accessToken = None
    mode = None
    backfill = None
    backfillSearch = None
    backfillSearchUrl = None
    minuteOfHourRate = None
    timezone = datetime.timedelta(days=1)
    dayOfMonthRate = None
    monthOfYearRate = None
    timeField = None
    threading = None
    profiler = None
    queueing = None
    zmqBaseUrl = None
    zmqBasePort = None
    maxIntervalsBeforeFlush = None
    maxQueueLength = None
    useOutputQueue = None

    __outputPlugins = { }
    __plugins = { }
    outputQueue = None
    generatorQueue = None

    ## Validations
    _validSettings = ['disabled', 'blacklist', 'spoolDir', 'spoolFile', 'breaker', 'sampletype' , 'interval',
                    'delay', 'count', 'bundlelines', 'earliest', 'latest', 'eai:acl', 'hourOfDayRate',
                    'dayOfWeekRate', 'randomizeCount', 'randomizeEvents', 'outputMode', 'fileName', 'fileMaxBytes',
                    'fileBackupFiles', 'index', 'source', 'sourcetype', 'host', 'hostRegex', 'projectID', 'accessToken', 
                    'mode', 'backfill', 'backfillSearch', 'eai:userName', 'eai:appName', 'timeMultiple', 'debug',
                    'minuteOfHourRate', 'timezone', 'dayOfMonthRate', 'monthOfYearRate', 'outputWorkers', 'generator',
                    'rater', 'generatorWorkers', 'timeField', 'sampleDir', 'threading', 'profiler', 'queueing',
                    'zmqBaseUrl', 'zmqBasePort', 'maxIntervalsBeforeFlush', 'maxQueueLength', 'verbose', 'useOutputQueue']
    _validTokenTypes = {'token': 0, 'replacementType': 1, 'replacement': 2}
    _validHostTokens = {'token': 0, 'replacement': 1}
    _validReplacementTypes = ['static', 'timestamp', 'replaytimestamp', 'random', 'rated', 'file', 'mvfile', 'integerid']
    _validOutputModes = [ ]
    _intSettings = ['interval', 'outputWorkers', 'generatorWorkers', 'zmqBasePort', 'maxIntervalsBeforeFlush',
                    'maxQueueLength']
    _floatSettings = ['randomizeCount', 'delay', 'timeMultiple']
    _boolSettings = ['disabled', 'randomizeEvents', 'bundlelines', 'profiler', 'useOutputQueue']
    _jsonSettings = ['hourOfDayRate', 'dayOfWeekRate', 'minuteOfHourRate', 'dayOfMonthRate', 'monthOfYearRate']
    _defaultableSettings = ['disabled', 'spoolDir', 'spoolFile', 'breaker', 'sampletype', 'interval', 'delay',
                            'count', 'bundlelines', 'earliest', 'latest', 'hourOfDayRate', 'dayOfWeekRate',
                            'randomizeCount', 'randomizeEvents', 'outputMode', 'fileMaxBytes', 'fileBackupFiles',
                            'splunkHost', 'splunkPort', 'splunkMethod', 'index', 'source', 'sourcetype', 'host', 'hostRegex',
                            'projectID', 'accessToken', 'mode', 'minuteOfHourRate', 'timeMultiple', 'dayOfMonthRate',
                            'monthOfYearRate', 'sessionKey', 'generator', 'rater', 'timeField', 'maxQueueLength',
                            'maxIntervalsBeforeFlush']
    _complexSettings = { 'sampletype': ['raw', 'csv'], 
                         'mode': ['sample', 'replay'],
                         'threading': ['thread', 'process'],
                         'queueing': ['python', 'zeromq']}

    def __init__(self):
        """Setup Config object.  Sets up Logging and path related variables."""
        # Rebind the internal datastore of the class to an Instance variable
        self.__dict__ = self.__sharedState
        if self._firsttime:
            # Setup logger
            # 12/8/13 CS Adding new verbose log level to make this a big more manageable
            DEBUG_LEVELV_NUM = 9 
            logging.addLevelName(DEBUG_LEVELV_NUM, "DEBUGV")
            logging.__dict__['DEBUGV'] = DEBUG_LEVELV_NUM
            def debugv(self, message, *args, **kws):
                # Yes, logger takes its '*args' as 'args'.
                if self.isEnabledFor(DEBUG_LEVELV_NUM):
                    self._log(DEBUG_LEVELV_NUM, message, args, **kws) 
            logging.Logger.debugv = debugv

            logger = logging.getLogger('eventgen')
            logger.propagate = False # Prevent the log messages from being duplicated in the python.log file
            logger.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
            streamHandler = logging.StreamHandler(sys.stderr)
            streamHandler.setFormatter(formatter)
            logger.addHandler(streamHandler)
            # logging.disable(logging.INFO)

            adapter = EventgenAdapter(logger, {'sample': 'null', 'module': 'config'})
            # Having logger as a global is just damned convenient
            self.logger = adapter

            # Determine some path names in our environment
            self.grandparentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.greatgrandparentdir = os.path.dirname(self.grandparentdir)

            # 1/11/14 CS Adding a initial config parsing step (this does this twice now, oh well, just runs once
            # per execution) so that I can get config before calling parse()

            c = ConfigParser()
            c.optionxform = str
            c.read([os.path.join(self.grandparentdir, 'default', 'eventgen.conf')])
            for s in c.sections():
                for i in c.items(s):
                    if i[0] == 'threading':
                        self.threading = i[1]
                    elif i[0] == 'queueing':
                        self.queueing = i[1]
                    elif i[0] == 'generatorQueueUrl':
                        self.generatorQueueUrl = i[1]
                    elif i[0] == 'outputQueueUrl':
                        self.outputQueueUrl = i[1]

            # Set a global variables to signal to our plugins the threading model without having 
            # to load config.  Kinda hacky, but easier than other methods.
            globals()['threadmodel'] = self.threading

            # Initialize plugins
            self.__outputPlugins = { }
            plugins = self.__initializePlugins(os.path.join(self.grandparentdir, 'lib', 'plugins', 'output'), self.__outputPlugins)
            self.outputQueue = Queue(100, self.threading)
            # Hard code the worker plugin mapping which we expect to be there and will never have a sample associated with it
            self.__plugins['OutputWorker'] = self.__outputPlugins['output.outputworker']
            self._validOutputModes.extend(plugins)

            plugins = self.__initializePlugins(os.path.join(self.grandparentdir, 'lib', 'plugins', 'generator'), self.__plugins)
            self.generatorQueue = Queue(10000, self.threading)
            self.__plugins['GeneratorWorker'] = self.__plugins['generator.generatorworker']
            self._complexSettings['generator'] = plugins

            plugins = self.__initializePlugins(os.path.join(self.grandparentdir, 'lib', 'plugins', 'rater'), self.__plugins)
            self._complexSettings['rater'] = plugins


            self._complexSettings['timezone'] = self._validateTimezone 

            self._complexSettings['count'] = self._validateCount

            self.generatorQueueSize = Counter(0, self.threading)
            self.outputQueueSize = Counter(0, self.threading)
            self.eventsSent = Counter(0, self.threading)
            self.bytesSent = Counter(0, self.threading)

            self.copyLock = threading.Lock() if self.threading == 'thread' else multiprocessing.Lock()

            self._firsttime = False
            self.intervalsSinceFlush = { }

    def __str__(self):
        """Only used for debugging, outputs a pretty printed representation of our Config"""
        # Eliminate recursive going back to parent
        temp = dict([ (key, value) for (key, value) in self.__dict__.items() if key != 'samples' and key != 'sampleTimers' and key != 'workers' ])
        return 'Config:'+pprint.pformat(temp)+'\nSamples:\n'+pprint.pformat(self.samples)

    def __repr__(self):
        return self.__str__()

    def __initializePlugins(self, dirname, plugins):
        """Load a python module dynamically and add to internal dictionary of plugins (only accessed by getPlugin)"""
        ret = [ ]
        
        # Include all plugin directories in sys.path for includes
        if not dirname in sys.path:
            sys.path.append(dirname)
         
        # Loop through all files in passed dirname looking for plugins
        for filename in os.listdir(dirname):
            filename = dirname + os.sep + filename
            # If the file exists
            if os.path.isfile(filename):
                # Split file into a base name plus extension
                basename = os.path.basename(filename)
                base, extension = os.path.splitext(basename)

                # If we're a python file and we don't start with _
                if extension == ".py" and not basename.startswith("_"):
                    # Import the module
                    module = __import__(base)
                    # Signal to the plugin by adding a module level variable which indicates
                    # our threading model, thread or process
                    module.__dict__.update({ 'threadmodel': self.threading })
                    # Load will now return a threading.Thread or multiprocessing.Process based object
                    plugin = module.load()

                    # set plugin to something like output.file or generator.default
                    pluginname = filename.split(os.sep)[-2] + '.' + base 
                    # self.logger.debugv("Filename: %s os.sep: %s pluginname: %s" % (filename, os.sep, pluginname))
                    plugins[pluginname] = plugin

                    # Return is used to determine valid configs, so only return the base name of the plugin
                    ret.append(base)

                    self.logger.debug("Loading module '%s' from '%s'" % (pluginname, basename))

                    # 12/3/13 If we haven't loaded a plugin right or we haven't initialized all the variables
                    # in the plugin, we will get an exception and the plan is to not handle it
                    if 'validSettings' in dir(plugin):
                        self._validSettings.extend(plugin.validSettings)
                    if 'defaultableSettings' in dir(plugin):
                        self._defaultableSettings.extend(plugin.defaultableSettings)
                    if 'intSettings' in dir(plugin):
                        self._intSettings.extend(plugin.intSettings)
                    if 'floatSettings' in dir(plugin):
                        self._floatSettings.extend(plugin.floatSettings)
                    if 'boolSettings' in dir(plugin):
                        self._boolSettings.extend(plugin.boolSettings)
                    if 'jsonSettings' in dir(plugin):
                        self._jsonSettings.extend(plugin.jsonSettings)
                    if 'complexSettings' in dir(plugin):
                        self._complexSettings.update(plugin.complexSettings)

        # Chop off the path we added
        sys.path = sys.path[0:-1]
        return ret


    def getPlugin(self, name):
        """Return a reference to a Python object (not an instance) referenced by passed name"""
        if not name in self.__plugins:
            raise KeyError('Plugin ' + name + ' not found')
        return self.__plugins[name]

    def __setPlugin(self, s):
        """Called during setup, assigns which output plugin to use based on configured outputMode"""
        # 12/2/13 CS Adding pluggable output modules, need to set array to map sample name to output plugin
        # module instances
        try:
            self.__plugins[s.name] = self.__outputPlugins['output.'+s.outputMode.lower()](s)
            plugin = self.__plugins[s.name]
        except KeyError:
            raise KeyError('Output plugin %s does not exist' % s.outputMode.lower())

    def makeSplunkEmbedded(self, sessionKey=None):
        """Setup operations for being Splunk Embedded.  This is legacy operations mode, just a little bit obfuscated now.
        We wait 5 seconds for a sessionKey or 'debug' on stdin, and if we time out then we run in standalone mode.
        If we're not Splunk embedded, we operate simpler.  No rest handler for configurations. We only read configs
        in our parent app's directory."""

        fileHandler = logging.handlers.RotatingFileHandler(os.environ['SPLUNK_HOME'] + '/var/log/splunk/eventgen.log', maxBytes=25000000, backupCount=5)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        fileHandler.setFormatter(formatter)
        # fileHandler.setLevel(logging.DEBUG)
        logobj = logging.getLogger('eventgen')
        logobj.handlers = [ ] # Remove existing StreamHandler if we're embedded
        logobj.addHandler(fileHandler)
        self.logger.info("Running as Splunk embedded")

        # 6/7/14 Add Metrics logger so we can output JSON metrics for Splunk
        fileHandler = logging.handlers.RotatingFileHandler(os.environ['SPLUNK_HOME'] + '/var/log/splunk/eventgen_metrics.log', maxBytes=25000000, backupCount=5)
        formatter = logging.Formatter('%(message)s')
        fileHandler.setFormatter(formatter)
        # fileHandler.setLevel(logging.DEBUG)
        logobj = logging.getLogger('eventgen_metrics')
        logobj.addHandler(fileHandler)
        import splunk.auth as auth
        import splunk.entity as entity
        # 5/7/12 CS For some reason Splunk will not import the modules into global in its copy of python
        # This is a hacky workaround, but it does fix the problem
        globals()['auth'] = locals()['auth']
        # globals()['bundle'] = locals()['bundle']
        globals()['entity'] = locals()['entity']
        # globals()['rest'] = locals()['rest']
        # globals()['util'] = locals()['util']

        if sessionKey == None:
            self.sessionKey = auth.getSessionKey('admin', 'changeme')
        else:
            self.sessionKey = sessionKey

        self.splunkEmbedded = True

    def getSplunkUrl(self, s):
        """
        Get Splunk URL.  If we're embedded in Splunk, get it from Splunk's Python libraries, otherwise get it from config.

        Returns a tuple of ( splunkUrl, splunkMethod, splunkHost, splunkPort )
        """
        if self.splunkEmbedded:
            try:
                import splunk.auth
                splunkUrl = splunk.auth.splunk.getLocalServerInfo()
                results = re.match('(http|https)://([^:/]+):(\d+).*', splunkUrl)
                splunkMethod = results.groups()[0]
                splunkHost = results.groups()[1]
                splunkPort = results.groups()[2]
            except:
                import traceback
                trace = traceback.format_exc()
                self.logger.error('Error parsing host from splunk.auth.splunk.getLocalServerInfo() for sample %s.  Stacktrace: %s' % (s.name, trace))
                raise ValueError('Error parsing host from splunk.auth.splunk.getLocalServerInfo() for sample %s' % s.name)
        else:
            # splunkMethod and splunkPort are defaulted so only check for splunkHost
            if s.splunkHost == None:
                self.logger.error("Splunk URL Requested but splunkHost not set for sample '%s'" % s.name)
                raise ValueError("Splunk URL Requested but splunkHost not set for sample '%s'" % s.name)  
                    
            splunkUrl = '%s://%s:%s' % (s.splunkMethod, s.splunkHost, s.splunkPort)
            splunkMethod = s.splunkMethod
            splunkHost = s.splunkHost
            splunkPort = s.splunkPort

        self.logger.debug("Getting Splunk URL: %s Method: %s Host: %s Port: %s" % (splunkUrl, splunkMethod, splunkHost, splunkPort))
        return (splunkUrl, splunkMethod, splunkHost, splunkPort)


    def parse(self):
        """Parse configs from Splunk REST Handler or from files.
        We get called manually instead of in __init__ because we need find out if we're Splunk embedded before
        we figure out how to configure ourselves.
        """
        self.logger.debug("Parsing configuration files.")
        self._buildConfDict()
        # Set defaults config instance variables to 'global' section
        # This establishes defaults for other stanza settings
        for key, value in self._confDict['global'].items():
            value = self._validateSetting('global', key, value)
            setattr(self, key, value)

        del self._confDict['global']
        if 'default' in self._confDict:
            del self._confDict['default']

        tempsamples = [ ]
        tempsamples2 = [ ]

        # Now iterate for the rest of the samples we've found
        # We'll create Sample objects for each of them
        for stanza, settings in self._confDict.items():
            sampleexists = False
            for sample in self.samples:
                if sample.name == stanza:
                    sampleexists = True

            # If we see the sample in two places, use the first and ignore the second
            if not sampleexists:
                s = Sample(stanza)
                for key, value in settings.items():
                    oldvalue = value
                    try:
                        value = self._validateSetting(stanza, key, value)
                    except ValueError:
                        # If we're improperly formatted, skip to the next item
                        continue
                    # If we're a tuple, then this must be a token
                    if type(value) == tuple:
                        # Token indices could be out of order, so we must check to
                        # see whether we have enough items in the list to update the token
                        # In general this will keep growing the list by whatever length we need
                        if(key.find("host.") > -1):
                            # self.logger.info("hostToken.{} = {}".format(value[1],oldvalue))
                            if not isinstance(s.hostToken, Token):
                                s.hostToken = Token(s)
                                # default hard-coded for host replacement
                                s.hostToken.replacementType = 'file'
                            setattr(s.hostToken, value[0], oldvalue)
                        else:
                            if len(s.tokens) <= value[0]:
                                x = (value[0]+1) - len(s.tokens)
                                s.tokens.extend([None for i in xrange(0, x)])
                            if not isinstance(s.tokens[value[0]], Token):
                                s.tokens[value[0]] = Token(s)
                            # logger.info("token[{}].{} = {}".format(value[0],value[1],oldvalue))
                            setattr(s.tokens[value[0]], value[1], oldvalue)
                    elif key == 'eai:acl':
                        setattr(s, 'app', value['app'])
                    else:
                        setattr(s, key, value)
                        # 6/22/12 CS Need a way to show a setting was set by the original
                        # config read
                        s._lockedSettings.append(key)
                        # self.logger.debug("Appending '%s' to locked settings for sample '%s'" % (key, s.name))


                # Validate all the tokens are fully setup, can't do this in _validateSettings
                # because they come over multiple lines
                # Don't error out at this point, just log it and remove the token and move on
                deleteidx = [ ]
                for i in xrange(0, len(s.tokens)):
                    t = s.tokens[i]
                    # If the index doesn't exist at all
                    if t == None:
                        self.logger.info("Token at index %s invalid" % i)
                        # Can't modify list in place while we're looping through it
                        # so create a list to remove later
                        deleteidx.append(i)
                    elif t.token == None or t.replacementType == None or t.replacement == None:
                        self.logger.info("Token at index %s invalid" % i)
                        deleteidx.append(i)
                newtokens = [ ]
                for i in xrange(0, len(s.tokens)):
                    if i not in deleteidx:
                        newtokens.append(s.tokens[i])
                s.tokens = newtokens

                # Must have eai:acl key to determine app name which determines where actual files are
                if s.app == None:
                    self.logger.error("App not set for sample '%s' in stanza '%s'" % (s.name, stanza))
                    raise ValueError("App not set for sample '%s' in stanza '%s'" % (s.name, stanza))

                # Set defaults for items not included in the config file
                for setting in self._defaultableSettings:
                    if getattr(s, setting) == None:
                        setattr(s, setting, getattr(self, setting))

                # Append to temporary holding list
                if not s.disabled:
                    s._priority = len(tempsamples)+1
                    tempsamples.append(s)

        # 6/22/12 CS Rewriting the config matching code yet again to handling flattening better.
        # In this case, we're now going to match all the files first, create a sample for each of them
        # and then take the match from the sample seen last in the config file, and apply settings from
        # every other match to that one.
        for s in tempsamples:
            # Now we need to match this up to real files.  May generate multiple copies of the sample.
            foundFiles = [ ]

            # 1/5/14 Adding a config setting to override sample directory, primarily so I can put tests in their own
            # directories
            if s.sampleDir == None:
                self.logger.debug("Sample directory not specified in config, setting based on standard")
                if self.splunkEmbedded and not STANDALONE:
                    self.sampleDir = os.path.join(self.greatgrandparentdir, s.app, 'samples')
                else:
                    self.sampleDir = os.path.join(os.getcwd(), 'samples')
                    if not os.path.exists(self.sampleDir):
                        newSampleDir = os.path.join(os.sep.join(os.getcwd().split(os.sep)[:-1]), 'samples')
                        self.logger.error("Path not found for samples '%s', trying '%s'" % (self.sampleDir, newSampleDir))
                        self.sampleDir = newSampleDir

                        if not os.path.exists(self.sampleDir):
                            newSampleDir = self.sampleDir = os.path.join(self.grandparentdir, 'samples')
                            self.logger.error("Path not found for samples '%s', trying '%s'" % (self.sampleDir, newSampleDir))
                            self.sampleDir = newSampleDir
            else:
                self.logger.debug("Sample directory specified in config, checking for relative")
                # Allow for relative paths to the base directory
                if not os.path.exists(s.sampleDir):
                    self.sampleDir = os.path.join(self.grandparentdir, s.sampleDir)
                else:
                    self.sampleDir = s.sampleDir


            # Now that we know where samples will be written,
            # Loop through tokens and load state for any that are integerid replacementType
            for token in s.tokens:
                if token.replacementType == 'integerid':
                    try:
                        stateFile = open(os.path.join(self.sampleDir, 'state.'+urllib.pathname2url(token.token)), 'rU')
                        token.replacement = stateFile.read()
                        stateFile.close()
                    # The file doesn't exist, use the default value in the config
                    except (IOError, ValueError):
                        token.replacement = token.replacement


            if os.path.exists(self.sampleDir):
                sampleFiles = os.listdir(self.sampleDir)
                for sample in sampleFiles:
                    results = re.match(s.name, sample)
                    if results != None:
                        samplePath = os.path.join(self.sampleDir, sample)
                        if os.path.isfile(samplePath):
                            self.logger.debug("Found sample file '%s' for app '%s' using config '%s' with priority '%s'; adding to list" \
                                % (sample, s.app, s.name, s._priority) )
                            foundFiles.append(samplePath)
            # If we didn't find any files, log about it
            if len(foundFiles) == 0:
                self.logger.warning("Sample '%s' in config but no matching files" % s.name)
                # 1/23/14 Change in behavior, go ahead and add the sample even if we don't find a file
                if not s.disabled:
                    tempsamples2.append(copy.deepcopy(s))
            for f in foundFiles:
                news = copy.deepcopy(s)
                news.filePath = f
                # 12/3/13 CS TODO These are hard coded but should be handled via the modular config system
                # Maybe a generic callback for all plugins which will modify sample based on the filename
                # found?
                # Override <SAMPLE> with real name
                if s.outputMode == 'spool' and s.spoolFile == self.spoolFile:
                    news.spoolFile = f.split(os.sep)[-1]
                if s.outputMode == 'file' and s.fileName == None and s.spoolFile == self.spoolFile:
                    news.fileName = os.path.join(s.spoolDir, f.split(os.sep)[-1])
                elif s.outputMode == 'file' and s.fileName == None and s.spoolFile != None:
                    news.fileName = os.path.join(s.spoolDir, s.spoolFile)
                # Override s.name with file name.  Usually they'll match unless we've been a regex
                # 6/22/12 CS Save original name for later matching
                news._origName = news.name
                news.name = f.split(os.sep)[-1]
                if not news.disabled:
                    tempsamples2.append(news)
                else:
                    self.logger.info("Sample '%s' for app '%s' is marked disabled." % (news.name, news.app))

        # Clear tempsamples, we're going to reuse it
        tempsamples = [ ]

        # We're now going go through the samples and attempt to apply any matches from other stanzas
        # This allows us to specify a wildcard at the beginning of the file and get more specific as we go on

        # Loop through all samples, create a list of the master samples
        for s in tempsamples2:
            foundHigherPriority = False
            othermatches = [ ]
            # If we're an exact match, don't go looking for higher priorities
            if not s.name == s._origName:
                for matchs in tempsamples2:
                    if matchs.filePath == s.filePath and s._origName != matchs._origName:
                        # We have a match, now determine if we're higher priority or not
                            # If this is a longer pattern or our match is an exact match
                            # then we're a higher priority match
                        if len(matchs._origName) > len(s._origName) or matchs.name == matchs._origName:
                            # if s._priority < matchs._priority:
                            self.logger.debug("Found higher priority for sample '%s' with priority '%s' from sample '%s' with priority '%s'" \
                                        % (s._origName, s._priority, matchs._origName, matchs._priority))
                            foundHigherPriority = True
                            break
                        else:
                            othermatches.append(matchs._origName)
            if not foundHigherPriority:
                self.logger.debug("Chose sample '%s' from samples '%s' for file '%s'" \
                            % (s._origName, othermatches, s.name))
                tempsamples.append(s)

        # Now we have two lists, tempsamples which contains only the highest priority matches, and
        # tempsamples2 which contains all matches.  We need to now flatten the config in order to
        # take all the configs which might match.

        # Reversing tempsamples2 in order to look from the bottom of the file towards the top
        # We want entries lower in the file to override entries higher in the file

        tempsamples2.reverse()

        # Loop through all samples
        for s in tempsamples:
            # Now loop through the samples we've matched with files to see if we apply to any of them
            for overridesample in tempsamples2:
                if s.filePath == overridesample.filePath and s._origName != overridesample._origName:
                    # Now we're going to loop through all valid settings and set them assuming
                    # the more specific object that we've matched doesn't already have them set
                    for settingname in self._validSettings:
                        if settingname not in ['eai:acl', 'blacklist', 'disabled', 'name']:
                            # 7/16/14 CS For some reason default settings are suddenly erroring
                            # not sure why, but lets just move on
                            try:
                                sourcesetting = getattr(overridesample, settingname)
                                destsetting = getattr(s, settingname)
                                # We want to check that the setting we're copying to hasn't been
                                # set, otherwise keep the more specific value
                                # 6/22/12 CS Added support for non-overrideable (locked) settings
                                # logger.debug("Locked settings: %s" % pprint.pformat(matchs._lockedSettings))
                                # if settingname in matchs._lockedSettings:
                                #     logger.debug("Matched setting '%s' in sample '%s' lockedSettings" \
                                #         % (settingname, matchs.name))
                                if (destsetting == None or destsetting == getattr(self, settingname)) \
                                        and sourcesetting != None and sourcesetting != getattr(self, settingname) \
                                        and not settingname in s._lockedSettings:
                                    self.logger.debug("Overriding setting '%s' with value '%s' from sample '%s' to sample '%s' in app '%s'" \
                                                    % (settingname, sourcesetting, overridesample._origName, s.name, s.app))
                                    setattr(s, settingname, sourcesetting)
                            except AttributeError:
                                pass

                    # Now prepend all the tokens to the beginning of the list so they'll be sure to match first
                    newtokens = copy.deepcopy(s.tokens)
                    # self.logger.debug("Prepending tokens from sample '%s' to sample '%s' in app '%s': %s" \
                    #             % (overridesample._origName, s.name, s.app, pprint.pformat(newtokens)))
                    newtokens.extend(copy.deepcopy(overridesample.tokens))
                    s.tokens = newtokens

        # We've added replay mode, so lets loop through the samples again and set the earliest and latest
        # settings for any samples that were set to replay mode
        for s in tempsamples:
            if s.mode == 'replay':
                self.logger.debug("Setting defaults for replay samples")
                s.earliest = 'now'
                s.latest = 'now'
                s.count = 1
                s.randomizeCount = None
                s.hourOfDayRate = None
                s.dayOfWeekRate = None
                s.minuteOfHourRate = None
                s.interval = 0
                # 12/29/13 CS Moved replay generation to a new replay generator plugin
                s.generator = 'replay'

            self.__setPlugin(s)
            self.intervalsSinceFlush[s.name] = Counter(0, self.threading)

        self.samples = tempsamples
        self._confDict = None

        self.logger.debug("Finished parsing.  Config str:\n%s" % self)


    def _validateSetting(self, stanza, key, value):
        """Validates settings to ensure they won't cause errors further down the line.
        Returns a parsed value (if the value is something other than a string).
        If we've read a token, which is a complex config, returns a tuple of parsed values."""
        self.logger.debugv("Validating setting for '%s' with value '%s' in stanza '%s'" % (key, value, stanza))
        if key.find('token.') > -1:
            results = re.match('token\.(\d+)\.(\w+)', key)
            if results != None:
                groups = results.groups()
                if groups[1] not in self._validTokenTypes:
                    self.logger.error("Could not parse token index '%s' token type '%s' in stanza '%s'" % \
                                    (groups[0], groups[1], stanza))
                    raise ValueError("Could not parse token index '%s' token type '%s' in stanza '%s'" % \
                                    (groups[0], groups[1], stanza))
                if groups[1] == 'replacementType':
                    if value not in self._validReplacementTypes:
                        self.logger.error("Invalid replacementType '%s' for token index '%s' in stanza '%s'" % \
                                    (value, groups[0], stanza))
                        raise ValueError("Could not parse token index '%s' token type '%s' in stanza '%s'" % \
                                    (groups[0], groups[1], stanza))
                return (int(groups[0]), groups[1])
        elif key.find('host.') > -1:
            results = re.match('host\.(\w+)', key)
            if results != None:
                groups = results.groups()
                if groups[0] not in self._validHostTokens:
                    self.logger.error("Could not parse host token type '%s' in stanza '%s'" % (groups[0], stanza))
                    raise ValueError("Could not parse host token type '%s' in stanza '%s'" % (groups[0], stanza))
                return (groups[0], value)
        elif key in self._validSettings:
            if key in self._intSettings:
                try:
                    value = int(value)
                except:
                    self.logger.error("Could not parse int for '%s' in stanza '%s'" % (key, stanza))
                    raise ValueError("Could not parse int for '%s' in stanza '%s'" % (key, stanza))
            elif key in self._floatSettings:
                try:
                    value = float(value)
                except:
                    self.logger.error("Could not parse float for '%s' in stanza '%s'" % (key, stanza))
                    raise ValueError("Could not parse float for '%s' in stanza '%s'" % (key, stanza))
            elif key in self._boolSettings:
                try:
                    # Splunk gives these to us as a string '0' which bool thinks is True
                    # ConfigParser gives 'false', so adding more strings
                    if value in ('0', 'false', 'False'):
                        value = 0
                    value = bool(value)
                except:
                    self.logger.error("Could not parse bool for '%s' in stanza '%s'" % (key, stanza))
                    raise ValueError("Could not parse bool for '%s' in stanza '%s'" % (key, stanza))
            elif key in self._jsonSettings:
                try:
                    value = json.loads(value)
                except:
                    self.logger.error("Could not parse json for '%s' in stanza '%s'" % (key, stanza))
                    raise ValueError("Could not parse json for '%s' in stanza '%s'" % (key, stanza))
            # 12/3/13 CS Adding complex settings, which is a dictionary with the key containing
            # the config item name and the value is a list of valid values or a callback function
            # which will parse the value or raise a ValueError if it is unparseable
            elif key in self._complexSettings:
                complexSetting = self._complexSettings[key]
                self.logger.debugv("Complex setting for '%s' in stanza '%s'" % (key, stanza))
                # Set value to result of callback, e.g. parsed, or the function should raise an error
                if isinstance(complexSetting, types.FunctionType) or isinstance(complexSetting, types.MethodType):
                    self.logger.debugv("Calling function for setting '%s' with value '%s'" % (key, value))
                    value = complexSetting(value)
                elif isinstance(complexSetting, list):
                    if not value in complexSetting:
                        self.logger.error("Setting '%s' is invalid for value '%s' in stanza '%s'" % (key, value, stanza))
                        raise ValueError("Setting '%s' is invalid for value '%s' in stanza '%s'" % (key, value, stanza))
            elif key == 'outputMode':
                if not value in self._validOutputModes:
                    self.logger.error("outputMode invalid in stanza '%s'" % stanza)
                    raise ValueError("outputMode invalid in stanza '%s'" % stanza)
        else:
            # Notifying only if the setting isn't valid and continuing on
            # This will allow future settings to be added and be backwards compatible
            self.logger.warning("Key '%s' in stanza '%s' is not a valid setting" % (key, stanza))
        return value

    def _validateTimezone(self, value):
        """Callback for complexSetting timezone which will parse and validate the timezone"""
        self.logger.debug("Parsing timezone '%s'" % (value))
        if value.find('local') >= 0:
            value = datetime.timedelta(days=1)
        else:
            try:
                # Separate the hours and minutes (note: minutes = the int value - the hour portion)
                if int(value) > 0:
                    mod = 100
                else:
                    mod = -100
                value = datetime.timedelta(hours=int(int(value) / 100.0), minutes=int(value) % mod )
            except:
                self.logger.error("Could not parse timezone '%s' for '%s'" % (value, key))
                raise ValueError("Could not parse timezone '%s' for '%s'" % (value, key))
        self.logger.debug("Parsed timezone '%s'" % (value))
        return value

    def _validateCount(self, value):
        """Callback to override count to -1 if set to 0 in the config, otherwise return int"""
        self.logger.debug("Validating count of %s" % value)
        # 5/13/14 CS Hack to take a zero count in the config and set it to a value which signifies
        # the special condition rather than simply being zero events, setting to -1       
        try:
            value = int(value)
        except:
            self.logger.error("Could not parse int for 'count' in stanza '%s'" % (key, stanza))
            raise ValueError("Could not parse int for 'count' in stanza '%s'" % (key, stanza))

        if value == 0:
            value = -1
        self.logger.debug("Count set to %d" % value)

        return value


    def _buildConfDict(self):
        """Build configuration dictionary that we will use """
        if self.splunkEmbedded and not STANDALONE:
            self.logger.info('Retrieving eventgen configurations from /configs/eventgen')
            self._confDict = entity.getEntities('configs/eventgen', count=-1, sessionKey=self.sessionKey)
        else:
            self.logger.info('Retrieving eventgen configurations with ConfigParser()')
            # We assume we're in a bin directory and that there are default and local directories
            conf = ConfigParser()
            # Make case sensitive
            conf.optionxform = str
            currentdir = os.getcwd()

            # If we're running standalone (and thusly using configParser)
            # only pick up eventgen-standalone.conf.
            conffiles = [ ]
            if len(sys.argv) > 1:
                if len(sys.argv[1]) > 0:
                    if os.path.exists(sys.argv[1]):
                        conffiles = [os.path.join(self.grandparentdir, 'default', 'eventgen.conf'),
                                    sys.argv[1]]
            if len(conffiles) == 0:
                conffiles = [os.path.join(self.grandparentdir, 'default', 'eventgen.conf'),
                            os.path.join(self.grandparentdir, 'local', 'eventgen.conf')]

            self.logger.debug('Reading configuration files for non-splunkembedded: %s' % conffiles)
            conf.read(conffiles)

            sections = conf.sections()
            ret = { }
            orig = { }
            for section in sections:
                ret[section] = dict(conf.items(section))
                # For compatibility with Splunk's configs, need to add the app name to an eai:acl key
                ret[section]['eai:acl'] = { 'app': self.grandparentdir.split(os.sep)[-1] }
                # orig[section] = dict(conf.items(section))
                # ret[section] = { }
                # for item in orig[section]:
                #     results = re.match('(token\.\d+)\.(\w+)', item)
                #     if results != None:
                #         ret[section][item] = orig[section][item]
                #     else:
                #         if item.lower() in [x.lower() for x in self._validSettings]:
                #             newitem = self._validSettings[[x.lower() for x in self._validSettings].index(item.lower())]
                #         ret[section][newitem] = orig[section][item]
            self._confDict = ret

        # Have to look in the data structure before normalization between what Splunk returns
        # versus what ConfigParser returns.
        logobj = logging.getLogger('eventgen')
        if self._confDict['global']['debug'].lower() == 'true' \
                or self._confDict['global']['debug'].lower() == '1':
            logobj.setLevel(logging.DEBUG)
        if self._confDict['global']['verbose'].lower() == 'true' \
                or self._confDict['global']['verbose'].lower() == '1':
            logobj.setLevel(logging.DEBUGV)
        self.logger.debug("ConfDict returned %s" % pprint.pformat(dict(self._confDict)))


    # Copied from http://danielkaes.wordpress.com/2009/06/04/how-to-catch-kill-events-with-python/
    def set_exit_handler(self, func):
        """Catch signals and call handle_exit when we're supposed to shut down"""
        if os.name == "nt":
            try:
                import win32api
                win32api.SetConsoleCtrlHandler(func, True)
            except ImportError:
                version = ".".join(map(str, sys.version_info[:2]))
                raise Exception("pywin32 not installed for Python " + version)
        else:
            import signal
            signal.signal(signal.SIGTERM, func)
            signal.signal(signal.SIGINT, func)
        
    def handle_exit(self, sig=None, func=None):
        """Clean up and shut down threads"""
        self.logger.info("Caught kill, exiting...")
        # Kill off zeromq context which kills any processing threads
        if self.queueing == 'zeromq':
            self.logger.info("Shutting down zeromq threads")
            self.zmqcontext.term()

        # Loop through all threads/processes and mark them for death
        # This does not actually kill the plugin, but they should check to see if
        # they are set to stop with every iteration
        for sampleTimer in self.sampleTimers:
            sampleTimer.stop()
        for worker in self.workers:
            worker.stop()

        self.logger.info("Exiting main thread.")
        sys.exit(0)

    def start(self):
        """Start up worker and zeromq threads"""

        if self.queueing == 'zeromq':
            self.logger.info("Starting zeromq processing threads")
            self.zmqcontext = zmq.Context()
            self.proxy1 = zmq.devices.ThreadProxy(zmq.PULL, zmq.PUSH)
            self.proxy1.bind_in(self.zmqBaseUrl+(':' if self.zmqBaseUrl.startswith('tcp') else '/')+str(self.zmqBasePort))
            self.proxy1.bind_out(self.zmqBaseUrl+(':' if self.zmqBaseUrl.startswith('tcp') else '/')+str(self.zmqBasePort+1))
            self.proxy1.start()
            self.proxy2 = zmq.devices.ThreadProxy(zmq.PULL, zmq.PUSH)
            self.proxy2.bind_in(self.zmqBaseUrl+(':' if self.zmqBaseUrl.startswith('tcp') else '/')+str(self.zmqBasePort+2))
            self.proxy2.bind_out(self.zmqBaseUrl+(':' if self.zmqBaseUrl.startswith('tcp') else '/')+str(self.zmqBasePort+3))
            self.proxy2.start()
        for x in xrange(0, self.outputWorkers):
            self.logger.info("Starting OutputWorker %d" % x)
            worker = self.getPlugin('OutputWorker')(x)
            worker.daemon = True
            worker.start()
            self.workers.append(worker)
        for x in xrange(0, self.generatorWorkers):
            self.logger.info("Starting GeneratorWorker %d" % x)
            worker = self.getPlugin('GeneratorWorker')(x, self.generatorQueue, self.outputQueue)
            worker.daemon = True
            worker.start()
            self.workers.append(worker)
        for sampleTimer in self.sampleTimers:
            sampleTimer.daemon = True
            sampleTimer.start()
            self.logger.info("Starting timer for sample '%s'" % sampleTimer.sample.name)
