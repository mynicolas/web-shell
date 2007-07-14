#!/usr/bin/python

""" WebShell Server 0.5.2 """

import array,time,glob,optparse,random,re
import os,sys,pty,signal,select,commands,threading,fcntl,termios,struct,pwd
import cgi,mimetypes

os.chdir(os.path.normpath(os.path.dirname(__file__)))
# Optional: Add QWeb in sys path
sys.path[0:0]=glob.glob('../../python')

import qweb

class Terminal:
	def __init__(self,w,h):
		self.width=w
		self.height=h
		self.init()
		self.reset()
	def init(self):
		self.esc_seq={
			"\x00": None,
			"\x05": self.esc_da,
			"\x07": None,
			"\x08": self.esc_0x08,
			"\x09": self.esc_0x09,
			"\x0a": self.esc_0x0a,
			"\x0b": self.esc_0x0a,
			"\x0c": self.esc_0x0a,
			"\x0d": self.esc_0x0d,
			"\x0e": None,
			"\x0f": None,
			"\x1b#8": None,
			"\x1b=": None,
			"\x1b>": None,
			"\x1b(0": None,
			"\x1b(A": None,
			"\x1b(B": None,
			"\x1b[c": self.esc_da,
			"\x1b[0c": self.esc_da,
			"\x1b]R": None,
			"\x1b7": self.esc_save,
			"\x1b8": self.esc_restore,
			"\x1bD": None,
			"\x1bE": None,
			"\x1bH": None,
			"\x1bM": self.esc_ri,
			"\x1bN": None,
			"\x1bO": None,
			"\x1bZ": self.esc_da,
			"\x1ba": None,
			"\x1bc": self.reset,
			"\x1bn": None,
			"\x1bo": None,
		}
		for k,v in self.esc_seq.items():
			if v==None:
				self.esc_seq[k]=self.esc_ignore
		# regex
		d={
			r'\[\??([0-9;]*)([@ABCDEFGHJKLMPXacdefghlmnqrstu`])' : self.csi_dispatch,
			r'\]([^\x07]+)\x07' : self.esc_ignore,
		}
		self.esc_re=[]
		for k,v in d.items():
			self.esc_re.append((re.compile('\x1b'+k),v))
		# define csi sequences
		self.csi_seq={
			'@': (self.csi_at,[1]),
			'`': (self.csi_G,[1]),
			'J': (self.csi_J,[0]),
			'K': (self.csi_K,[0]),
		}
		for i in [i[4] for i in dir(self) if i.startswith('csi_') and len(i)==5]:
			if not self.csi_seq.has_key(i):
				self.csi_seq[i]=(getattr(self,'csi_'+i),[1])
		# Init 0-256 to latin1 and html translation table
		self.trl1=""
		for i in range(256):
			if i<32:
				self.trl1+=" "
			elif i<127 or i>160:
				self.trl1+=chr(i)
			else:
				self.trl1+="?"
		self.trhtml=""
		for i in range(256):
			if i==0x0a or (i>32 and i<127) or i>160:
				self.trhtml+=chr(i)
			elif i<=32:
				self.trhtml+="\xa0"
			else:
				self.trhtml+="?"
	def reset(self,s=""):
		self.scr=array.array('i',[0x000700]*(self.width*self.height))
		self.st=0
		self.sb=self.height-1
		# Cursor position
		self.cx_bak=self.cx=0
		self.cy_bak=self.cy=0
		self.cl=0
		# Color mask
		self.sgr=0x000700
		# Buffer
		self.buf=""
		self.outbuf=""
		self.last_html=""
	def peek(self,y1,x1,y2,x2):
		return self.scr[self.width*y1+x1:self.width*y2+x2]
	def poke(self,y,x,s):
		pos=self.width*y+x
		self.scr[pos:pos+len(s)]=s
	def zero(self,y1,x1,y2,x2):
		w=self.width*(y2-y1)+x2-x1+1
		z=array.array('i',[0x000700]*w)
		self.scr[self.width*y1+x1:self.width*y2+x2+1]=z
	def scroll_up(self,y1,y2):
		self.poke(y1,0,self.peek(y1+1,0,y2,self.width))
		self.zero(y2,0,y2,self.width-1)
	def scroll_down(self,y1,y2):
		self.poke(y1+1,0,self.peek(y1,0,y2-1,self.width))
		self.zero(y1,0,y1,self.width-1)
	def scroll_right(self,y,x):
		self.poke(y,x+1,self.peek(y,x,y,self.width))
		self.zero(y,x,y,x)
	def cursor_down(self):
		if self.cy>=self.st and self.cy<=self.sb:
			self.cl=0
			q,r=divmod(self.cy+1,self.sb+1)
			if q:
				self.scroll_up(self.st,self.sb)
				self.cy=self.sb
			else:
				self.cy=r
	def cursor_right(self):
		q,r=divmod(self.cx+1,self.width)
		if q:
			self.cl=1
		else:
			self.cx=r
	def echo(self,c):
		if self.cl:
			self.cursor_down()
			self.cx=0
		self.scr[(self.cy*self.width)+self.cx]=self.sgr|ord(c)
		self.cursor_right()
	def esc_0x08(self,s):
		self.cx=max(0,self.cx-1)
	def esc_0x09(self,s):
		x=self.cx+8
		q,r=divmod(x,8)
		self.cx=(q*8)%self.width
	def esc_0x0a(self,s):
		self.cursor_down()
	def esc_0x0d(self,s):
		self.cl=0
		self.cx=0
	def esc_save(self,s):
		self.cx_bak=self.cx
		self.cy_bak=self.cy
	def esc_restore(self,s):
		self.cx=self.cx_bak
		self.cy=self.cy_bak
		self.cl=0
	def esc_da(self,s):
		self.outbuf="\x1b[?6c"
	def esc_ri(self,s):
		self.cy=max(self.st,self.cy-1)
		if self.cy==self.st:
			self.scroll_down(self.st,self.sb)
	def esc_ignore(self,*s):
		pass
#		print "term:ignore: %s"%repr(s)
	def csi_dispatch(self,seq,mo):
	# CSI sequences
		s=mo.group(1)
		c=mo.group(2)
		f=self.csi_seq.get(c,None)
		if f:
			try:
				l=[min(int(i),1024) for i in s.split(';') if len(i)<4]
			except ValueError:
				l=[]
			if len(l)==0:
				l=f[1]
			f[0](l)
#		else:
#			print 'csi ignore',c,l
	def csi_at(self,l):
		for i in range(l[0]):
			self.scroll_right(self.cy,self.cx)
	def csi_A(self,l):
		self.cy=max(self.st,self.cy-l[0])
	def csi_B(self,l):
		self.cy=min(self.sb,self.cy+l[0])
	def csi_C(self,l):
		self.cx=min(self.width-1,self.cx+l[0])
		self.cl=0
	def csi_D(self,l):
		self.cx=max(0,self.cx-l[0])
		self.cl=0
	def csi_E(self,l):
		self.csi_B(l)
		self.cx=0
		self.cl=0
	def csi_F(self,l):
		self.csi_A(l)
		self.cx=0
		self.cl=0
	def csi_G(self,l):
		self.cx=min(self.width,l[0])-1
	def csi_H(self,l):
		if len(l)<2: l=[1,1]
		self.cx=min(self.width,l[1])-1
		self.cy=min(self.height,l[0])-1
		self.cl=0
	def csi_J(self,l):
		if l[0]==0:
			self.zero(self.cy,self.cx,self.height-1,self.width-1)
		elif l[0]==1:
			self.zero(0,0,self.cy,self.cx)
		elif l[0]==2:
			self.zero(0,0,self.height-1,self.width-1)
	def csi_K(self,l):
		if l[0]==0:
			self.zero(self.cy,self.cx,self.cy,self.width-1)
		elif l[0]==1:
			self.zero(self.cy,0,self.cy,self.cx)
		elif l[0]==2:
			self.zero(self.cy,0,self.cy,self.width-1)
	def csi_L(self,l):
		for i in range(l[0]):
			if self.cy<self.sb:
				self.scroll_down(self.cy,self.sb)
	def csi_M(self,l):
		if self.cy>=self.st and self.cy<=self.sb:
			for i in range(l[0]):
				self.scroll_up(self.cy,self.sb)
	def csi_P(self,l):
		w,cx,cy=self.width,self.cx,self.cy
		end=self.peek(cy,cx,cy,w)
		self.csi_K([0])
		self.poke(cy,cx,end[l[0]:])
	def csi_X(self,l):
		self.zero(self.cy,self.cx,self.cy,self.cx+l[0])
	def csi_a(self,l):
		self.csi_C(l)
	def csi_c(self,l):
		#'\x1b[?0c' 0-8 cursor size
		pass
	def csi_d(self,l):
		self.cy=min(self.height,l[0])-1
	def csi_e(self,l):
		self.csi_B(l)
	def csi_f(self,l):
		self.csi_H(l)
	def csi_h(self,l):
		if l[0]==4:
			pass
#			print "insert on"
	def csi_l(self,l):
		if l[0]==4:
			pass
#			print "insert off"
	def csi_m(self,l):
		# Select graphic rendition
		for i in l:
			if i==0 or i==39 or i==49 or i==27:
				self.sgr=0x000700
##			elif i==1:
				# Bold
##				self.sgr=(self.sgr|0x000800)
			elif i==7:
				# Negative image
				self.sgr=0x070000
			elif i>=30 and i<=37:
				# Foreground colour
				c=i-30
				self.sgr=(self.sgr&0xff08ff)|(c<<8)
			elif i>=40 and i<=47:
				# Background colour
				c=i-40
				self.sgr=(self.sgr&0x00ffff)|(c<<16)
#			else:
#				print "CSI sgr ignore",l,i
#		print 'sgr: %r %x'%(l,self.sgr)
	def csi_r(self,l):
		if len(l)<2: l=[0,self.height]
		self.st=min(self.height-1,l[0]-1)
		self.sb=min(self.height-1,l[1]-1)
		self.sb=max(self.st,self.sb)
	def csi_s(self,l):
		self.esc_save(0)
	def csi_u(self,l):
		self.esc_restore(0)
	def escape(self):
		e=self.buf
		if len(e)>32:
#			print "error %r"%e
			self.buf=""
		elif e in self.esc_seq:
			self.esc_seq[e](e)
			self.buf=""
		else:
			for r,f in self.esc_re:
				mo=r.match(e)
				if mo:
					f(e,mo)
					self.buf=""
					break
#		if self.buf=='': print "ESC %r\n"%e
	def write(self,s):
		for i in s:
			if len(self.buf) or (i in self.esc_seq):
				self.buf+=i
				self.escape()
			elif i == '\x1b':
				self.buf+=i
			else:
				self.echo(i)
	def read(self):
		b=self.outbuf
		self.outbuf=""
		return b
#	def dump(self):
#		r=''
#		for i in self.scr:
#			r+=chr(i&255)
#		return r
#	def dumplatin1(self):
#		return self.dump().translate(self.trl1)
	def dumphtml(self):
		h=self.height
		w=self.width
		r=""
		span=""
		span_bg,span_fg=-1,-1
		for i in range(h*w):
			q,c=divmod(self.scr[i],256)
			bg,fg=divmod(q,256)
			# Cursor
			if i==self.cy*w+self.cx:
				bg=8
			if (bg!=span_bg or fg!=span_fg or i==h*w-1):
				if len(span):
					r+='<span class="f%x b%x">%s</span>'%(span_fg,span_bg,cgi.escape(span.translate(self.trhtml)))
				span=""
				span_bg,span_fg=bg,fg
			span+=chr(c)
			if i%w==w-1:
				span+='\n'
		r='<?xml version="1.0" encoding="ISO-8859-1"?><pre class="term">%s</pre>'%r
		if self.last_html==r:
			return '<?xml version="1.0"?><idem></idem>'
		else:
			self.last_html=r
#			print self
			return r
#	def __repr__(self):
#		d=self.dumplatin1()
#		r=""
#		for i in range(self.height):
#			r+="|%s|\n"%d[self.width*i:self.width*(i+1)]
#		return r

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
			# Check max ttys
			# TO-DO
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
			# Safe way to make it work in BSD and Linux
			try:
				os.system(cmd)
			except (IOError,OSError):
				pass
			os._exit(0)
		else:
#			fcntl.fcntl(fd,fcntl.F_SETFL,os.O_NONBLOCK)
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
		dump=self.session[sid]['term'].dumphtml()
		self.session[sid]['time']=time.time()
		return dump
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
	def __init__(self,cmd=None,index_file='webshell.html',max_tty=32):
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
			self.multiplex.proc_keepalive(sid,w,h)
			if k:
				self.multiplex.proc_write(sid,k)
			time.sleep(0.002)
			dump=self.multiplex.proc_dump(sid)
			req.response_headers['Content-Type']='text/xml'
			if dump:
				req.write(dump)
				req.response_gzencode=1
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
	parser.add_option("-m", "--max-ttys", dest="max_tty", default="32", help="Set the maximum number of tty sessions (default: 32)")
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
	webshell=WebShell(o.cmd,o.index_file,o.max_tty)
	try:
		qweb.QWebWSGIServer(webshell,ip='localhost',port=int(o.port),threaded=0,log=o.log).serve_forever()
	except KeyboardInterrupt,e:
		print 'Stopped'
	webshell.stop()

if __name__ == '__main__':
	main()
