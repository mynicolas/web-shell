#!/usr/bin/python

""" WebShell Server 0.5.3 """

import array,time,glob,optparse,random,re
import os,sys,pty,signal,select,commands,threading,fcntl,termios,struct,pwd
import cgi,mimetypes

os.chdir(os.path.normpath(os.path.dirname(__file__)))
# Optional: Add QWeb in sys path
sys.path[0:0]=glob.glob('../../python')

import qweb

class Terminal:
	def __init__(self,w,h):
		self.w=w
		self.h=h
		self.init()
		self.reset()
		self.write('Debug message: this is an experimental dumb terminal\n\r')
	def init(self):
		pass
	def reset(self):
		# Attribute mask (Foreground, Background): 0x00FB0000
		self.attr=0x700000
		# Screen
		self.screen=array.array('i',[self.attr|0x20]*self.w*self.h)
		self.area_y0=0
		self.area_y1=self.h
		# Cursor position
		self.cx=0
		self.cy=0
		# Buffers
		self.ctrl_in=""
		self.ctrl_out=""
		# Caches
		self.dump_cache=""
	# Dumb terminal functions
	def peek(self,y0,x0,y1,x1):
		return self.screen[self.w*y0+x0:self.w*(y1-1)+x1]
	def poke(self,y,x,s):
		pos=self.w*y+x
		self.screen[pos:pos+len(s)]=s
	def clear(self,y0,x0,y1,x1):
		n=self.w*(y1-y0-1)+(x1-x0)
		self.poke(y0,x0,array.array('i',[self.attr|0x20]*n))
	def scroll_up(self,y0,y1):
		self.poke(y0,0,self.peek(y0+1,0,y1,self.w))
		self.clear(y1-1,0,y1,self.w)
	def scroll_down(self,y0,y1):
		self.poke(y0+1,0,self.peek(y0,0,y1-1,self.w))
		self.clear(y0,0,y0+1,self.w)
	def scroll_line_right(self,y,x):
		self.poke(y,x+1,self.peek(y,x,y+1,self.w-1))
		self.clear(y,x,y+1,x+1)
	def cursor_down(self):
		if self.cy>=self.area_y0 and self.cy<self.area_y1:
			if self.cy==(self.area_y1-1):
				self.scroll_up(self.area_y0,self.area_y1)
			else:
				self.cy=self.cy+1
	def cursor_right(self):
		delta_y,self.cx=divmod(self.cx+1,self.w)
		if delta_y:
			self.cursor_down()
	def ctrl_bs(self):
		delta_y,self.cx=divmod(self.cx-1,self.w)
		self.cy=max(self.area_y0,self.cy+delta_y)
	def ctrl_tab(self):
		tab,sub=divmod(self.cx+8,8)
		self.cx=min(tab*8,self.w-1)
	def ctrl_lf(self):
		self.cursor_down()
	def ctrl_cr(self):
		self.cx=0
	def echo(self,char):
		self.poke(self.cy,self.cx,array.array('i',[self.attr|char]))
		self.cursor_right()
		if char>=0x400:
			# Double width characters
			self.cursor_right()
			
	# ECMA-48 terminal
	def ctrl_esc(self,char):
		return False

	# External interface
	def set_size(self,w,h):
		if w<2 or w>256 or h<2 or h>256:
			return False
		self.w=w
		self.h=h
		reset()
		return True
	def read(self):
		d=self.ctrl_out
		self.ctrl_out=""
		return d
	def write(self,d):
		d=unicode(d,'utf8')
		for c in d:
			char = ord(c)
			if char==8:
				self.ctrl_bs()
			elif char==9:
				self.ctrl_tab()
			elif char==10:
				self.ctrl_lf()
			elif char==13:
				self.ctrl_cr()
			elif not self.ctrl_esc(char):
				if char>=0x20 and char<=0xffff:
					self.echo(char)
	def dump(self):
		pre=u""
		bg_,fg_=-1,-1
		is_wide=False
		for y in range(0,self.h):
			for x in range(0,self.w):
				if is_wide:
					is_wide=False
					continue
				attr,char=divmod(self.screen[y*self.w+x],0x10000)
				fg,bg=divmod(attr,0x10)
				# Cursor
				if self.cy==y and self.cx==x:
					bg=8
				# Color
				if fg!=fg_ or bg!=bg_:
					if x>0 or y>0:
						pre+=u'</span>'
					pre+=u'<span class="f%x b%x">'%(fg,bg)
					fg_,bg_=fg,bg
				# Character
				if char==38:
					pre+='&amp;'
				elif char==60:
					pre+='&lt;'
				elif char==62:
					pre+='&gt;'
				else:
					pre+=unichr(char)
					if char>=0x400:
						is_wide=True
			pre+="\n"
		# Escape HTML characters
		pre=pre.encode('utf-8')
		pre+='</span>'
		# Cache dump
		dump='<?xml version="1.0" encoding="UTF-8"?><pre class="term">%s</pre>'%pre
		if self.dump_cache==dump:
			return '<?xml version="1.0"?><idem></idem>'
		else:
			self.dump_cache=dump
			return dump

class SynchronizedMethod:
	def __init__(self,lock,orig):
		self.lock=lock
		self.orig=orig
	def __call__(self,*l):
		self.lock.acquire()
		try:
			r=self.orig(*l)
		finally:
			self.lock.release()
			pass
		return r

class Multiplex:
	def __init__(self,cmd=None):
		# Set Linux signal handler
		uname=commands.getoutput('uname')
		if uname=='Linux':
			self.sigchldhandler=signal.signal(signal.SIGCHLD,signal.SIG_IGN)
		# Session
		self.session={}
		self.cmd=cmd
		# Synchronize methods
		self.lock=threading.RLock()
		for name in ['stop','proc_keepalive','proc_spawn','proc_kill','proc_read','proc_write','proc_dump']:
			orig=getattr(self,name)
			setattr(self,name,SynchronizedMethod(self.lock,orig))
		# Supervisor thread
		self.signal_stop=0
		self.thread=threading.Thread(target=self.proc_thread)
		self.thread.start()
	def stop(self):
		# Stop supervisor thread
		self.signal_stop=1
		self.thread.join()
	def proc_keepalive(self,sid,w,h):
		if not sid in self.session:
			# Start a new session
			self.session[sid]={'state':'unborn','term':Terminal(w,h),'time':time.time(),'w':w,'h':h}
			return self.proc_spawn(sid)
		elif self.session[sid]['state']=='alive':
			self.session[sid]['time']=time.time()
			# Update terminal size
			if self.session[sid]['w']!=w or self.session[sid]['h']!=h:
				try:
					fcntl.ioctl(self.session[sid]['fd'],termios.TIOCSWINSZ,struct.pack("HHHH",h,w,0,0))
				except (IOError,OSError):
					pass
				self.session[sid]['term'].set_size(w,h)
				self.session[sid]['w']=w
				self.session[sid]['h']=h
			return True
		else:
			return False
	def proc_spawn(self,sid):
		try:
			# Fork new process
			pid,fd=os.forkpty()
		except (IOError,OSError):
			self.session[sid]['state']='dead'
			return False
		if pid==0:
			if self.cmd:
				cmd=self.cmd
			elif os.getuid()==0:
				cmd='/bin/login'
			else:
				sys.stdout.write("Login: ")
				login=sys.stdin.readline().strip()
				if re.match('^[0-9A-Za-z-_. ]+$',login):
					cmd='ssh'
					cmd+=' -oPreferredAuthentications=password'
					cmd+=' -oNoHostAuthenticationForLocalhost=yes'
					cmd+=' -oLogLevel=FATAL'
					cmd+=' -F/dev/null -l' + login +' localhost'
				else:
					os._exit(0)
			# Safe way to make it work under BSD and Linux
			try:
				os.system(cmd)
			except (IOError,OSError):
				pass
			os._exit(0)
		else:
			# Set file control
			fcntl.fcntl(fd,fcntl.F_SETFL,os.O_NONBLOCK)
			# Set terminal size
			try:
				fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack("HHHH",self.session[sid]['h'],self.session[sid]['w'],0,0))
			except (IOError,OSError):
				pass
			self.session[sid]['pid']=pid
			self.session[sid]['fd']=fd
			self.session[sid]['state']='alive'
			return True
	def proc_stop(self,sid):
		# Remove zombie (when process exited on its own)
		if sid not in self.session:
			return False
		elif self.session[sid]['state']=='alive':
			try:
				os.close(self.session[sid]['fd'])
			except (IOError,OSError):
				pass
			try:
				os.waitpid(self.session[sid]['pid'],0)
			except (IOError,OSError):
				pass
			del self.session[sid]['fd']
			del self.session[sid]['pid']
		self.session[sid]['state']='dead'
		return True
	def proc_kill(self,sid):
		# Kill process and session
		if sid not in self.session:
			return False
		elif self.session[sid]['state']=='alive':
			try:
				os.close(self.session[sid]['fd'])
			except (IOError,OSError):
				pass
			try:
				os.kill(self.session[sid]['pid'],signal.SIGTERM)
				os.waitpid(self.session[sid]['pid'],0)
			except (IOError,OSError):
				pass
		del self.session[sid]
		return True
	def proc_read(self,sid):
		# Read from process
		if sid not in self.session:
			return False
		elif self.session[sid]['state']=='dead':
			return False
		fd = self.session[sid]['fd']
		try:
			d=os.read(fd,65536)
			if not d:
				# Process finished, BSD
				return False
# DEBUG CODE
			else:
				fileHandle=open('/tmp/out.txt','a')
				fileHandle.write(d)
				fileHandle.close()
		except (IOError,OSError):
			# Process finished, Linux
			return False
		term=self.session[sid]['term']
		term.write(d)
		# Read terminal response
		d=term.read()
		if d:
			try:
				os.write(fd,d)
			except (IOError,OSError):
				return False
		return True
	def proc_write(self,sid,d):
		# Write to process
		if sid not in self.session:
			return False
		elif self.session[sid]['state']=='dead':
			return False
		try:
			fd=self.session[sid]['fd']
			os.write(fd,d)
		except (IOError,OSError):
			return False
		return True
	def proc_dump(self,sid):
		if sid not in self.session:
			return False
		return self.session[sid]['term'].dump()
	def proc_thread(self):
		while not self.signal_stop:
#			print self.session
			# Process management
			now=time.time()
			fds=[]
			fd2sid={}
			for sid in self.session.keys():
				then=self.session[sid]['time']
				if (now-then)>10:
					self.proc_kill(sid)
				else:
					if self.session[sid]['state']=='alive':
						fds.append(self.session[sid]['fd'])
						fd2sid[self.session[sid]['fd']]=sid
			# Read pipes
			try:
				i,o,e=select.select(fds, [], [], 1.0)
			except (IOError,OSError):
				i=[]
			for fd in i:
				sid=fd2sid[fd]
				if not self.proc_read(sid):
					self.proc_stop(sid)
			if len(i):
				time.sleep(0.002)
		for sid in self.session.keys():
			self.proc_kill(sid)

class WebShell:
	def __init__(self,cmd=None,index_file='webshell.html'):
		self.files={}
		for i in ['css','html','js','png']:
			for j in glob.glob('*.%s'%i):
				self.files[j]=file(j).read()
		self.files['index']=file(index_file).read()
		self.mime = mimetypes.types_map.copy()
		self.mime['.html']= 'text/html; charset=UTF-8'
		self.multiplex = Multiplex(cmd)
	def __call__(self, environ, start_response):
		req = qweb.QWebRequest(environ, start_response,session=None)
		if req.PATH_INFO.endswith('/u'):
			sid=req.REQUEST["s"]
			k=req.REQUEST["k"]
			w=req.REQUEST.int("w")
			h=req.REQUEST.int("h")
			if self.multiplex.proc_keepalive(sid,w,h):
				if k:
					self.multiplex.proc_write(sid,k)
				time.sleep(0.002)
				req.write(self.multiplex.proc_dump(sid))
				req.response_gzencode=1
				req.response_headers['Content-Type']='text/xml'
			else:
				req.write('<?xml version="1.0"?><idem></idem>')
		else:
			n=os.path.basename(req.PATH_INFO)
			if n in self.files:
				req.response_headers['Content-Type'] = self.mime.get(os.path.splitext(n)[1].lower(), 'application/octet-stream')
				req.write(self.files[n])
			else:
				req.response_headers['Content-Type'] = 'text/html; charset=UTF-8'
				req.write(self.files['index'])
		return req
	def stop(self):
		self.multiplex.stop()

def main():
	parser=optparse.OptionParser()
	parser.add_option("-p", "--port", dest="port", default="8022", help="Set the TCP port (default: 8022)")
	parser.add_option("-c", "--command", dest="cmd", default=None,help="set the command (default: /bin/login or ssh localhost)")
	parser.add_option("-l", "--log", action="store_true", dest="log",default=0,help="log requests to stderr (default: quiet mode)")
	parser.add_option("-d", "--daemon", action="store_true", dest="daemon", default=0, help="run as daemon in the background")
	parser.add_option("-P", "--pidfile",dest="pidfile",default="/var/run/webshell.pid",help="set the pidfile (default: /var/run/webshell.pid)")
	parser.add_option("-i", "--index", dest="index_file", default="webshell.html",help="default index file (default: webshell.html)")
	parser.add_option("-u", "--uid", dest="uid", help="Set the daemon's user id")
	(o,a)=parser.parse_args()
	if o.daemon:
		pid=os.fork()
		if pid==0:
#			os.setsid() ?
			os.setpgrp()
			nullin = file('/dev/null', 'r')
			nullout = file('/dev/null', 'w')
			os.dup2(nullin.fileno(), sys.stdin.fileno())
			os.dup2(nullout.fileno(), sys.stdout.fileno())
			os.dup2(nullout.fileno(), sys.stderr.fileno())
			if os.getuid()==0 and o.uid:
				try:
					os.setuid(int(o.uid))
				except:
					os.setuid(pwd.getpwnam(o.uid).pw_uid)
		else:
			try:
				file(o.pidfile,'w+').write(str(pid)+'\n')
			except:
				pass
			print 'WebShell at http://localhost:%s/ pid: %d' % (o.port,pid)
			sys.exit(0)
	else:
		print 'WebShell at http://localhost:%s/' % o.port
	webshell=WebShell(o.cmd,o.index_file)
	try:
		qweb.QWebWSGIServer(webshell,ip='localhost',port=int(o.port),threaded=0,log=o.log).serve_forever()
	except KeyboardInterrupt,e:
		print 'Stopped'
	webshell.stop()

if __name__ == '__main__':
	main()
