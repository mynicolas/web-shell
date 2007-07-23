#!/usr/bin/python

""" WebShell Server """
""" Released under the GPL 2.0 by Marc S. Ressl """

version="0.7.0"

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
		self.reset_hard()
		
	# Reset functions
	def reset_hard(self):
		# Attribute mask: 0x0XFB0000
		#  X: Bit 0 - Underlined
		#     Bit 1 - Negative
		#     Bit 2 - Concealed
		#  F: Foreground
		#  B: Background
		self.attr=0x00fe0000
		# Scroll parameters
		self.scroll_area_y0=0
		self.scroll_area_y1=self.h
		# UTF-8 decoder
		self.utf8_units_count=0
		self.utf8_units_received=0
		self.utf8_char=0
		# Character map
		self.vt100_charmap=0
		# Modes
		self.vt100_mode_insert=False
		self.vt100_mode_inverse=False
		self.vt100_mode_origin=False
		self.vt100_mode_autowrap=True
		self.vt100_mode_lfnewline=False
		self.vt100_mode_cursor=True
		self.vt100_mode_alt_screen=False
		self.vt100_mode_column_switch=False
		# Saved cursor data
		self.vt100_saved_cx=0
		self.vt100_saved_cy=0
		self.vt100_saved_attr=self.attr
		self.vt100_saved_charmap=self.vt100_charmap
		self.vt100_saved_mode_origin=self.vt100_mode_origin
		# Control sequences
		self.vt100_parse_len=0
		self.vt100_parse_state=""
		self.vt100_parse_func=""
		self.vt100_parse_param=""
		# Buffers
		self.vt100_out=""
		# Caches
		self.dump_cache=""
		self.reset()
	def reset(self):
		# Screen
		self.screen=array.array('i',[self.attr|0x20]*self.w*self.h)
		self.screen2=array.array('i',[self.attr|0x20]*self.w*self.h)
		# Cursor position
		self.cx=0
		self.cy=0
		# Tab stops
		self.tab_stops=range(0,self.w,8)

	# UTF-8 functions
	def utf8_decode(self, d):
#		try:
#			d=unicode(d,'utf-8')
#		except UnicodeDecodeError:

		o=''
		for c in d:
			char=ord(c)
			if self.utf8_units_count!=self.utf8_units_received:
				self.utf8_units_received+=1
				if (char&0xc0)==0x80:
					self.utf8_char=(self.utf8_char<<6)|(char&0x3f)
					if self.utf8_units_count==self.utf8_units_received:
						o+=unichr(self.utf8_char)
						self.utf8_units_count=self.utf8_units_received=0
				else:
					o+='?'
					while self.utf8_units_received:
						o+='?'
						self.utf8_units_received-=1
					self.utf8_units_count=0
			else:
				if (char&0x80)==0x00:
					o+=c
				elif (char&0xe0)==0xc0:
					self.utf8_units_count=1
					self.utf8_char=char&0x1f
				elif (char&0xf0)==0xe0:
					self.utf8_units_count=2
					self.utf8_char=char&0x0f
				elif (char&0xf8)==0xf0:
					self.utf8_units_count=3
					self.utf8_char=char&0x07
				else:
					o+='?'
					self.utf8_units_count=0
		return o
	def utf8_charwidth(self,char):
		if char>=0x2e80:
			return 2
		else:
			return 1
		
	# Low-level terminal functions
	def peek(self,y0,x0,y1,x1):
		return self.screen[self.w*y0+x0:self.w*(y1-1)+x1]
	def poke(self,y,x,s):
		pos=self.w*y+x
		self.screen[pos:pos+len(s)]=s
	def fill(self,y0,x0,y1,x1,char):
		n=self.w*(y1-y0-1)+(x1-x0)
		self.poke(y0,x0,array.array('i',[char]*n))
	def clear(self,y0,x0,y1,x1):
		self.fill(y0,x0,y1,x1,self.attr|0x20)
	
	# Scrolling functions
	def scroll_area_up(self,y0,y1,n=1):
		n=min(y1-y0,n)
		self.poke(y0,0,self.peek(y0+n,0,y1,self.w))
		self.clear(y1-n,0,y1,self.w)
	def scroll_area_down(self,y0,y1,n=1):
		n=min(y1-y0,n)
		self.poke(y0+n,0,self.peek(y0,0,y1-n,self.w))
		self.clear(y0,0,y0+n,self.w)
	def scroll_area_set(self,y0,y1):
		y0=max(0,min(self.h-1,y0))
		y1=max(1,min(self.h,y1))
		if y1>y0:
			self.scroll_area_y0=y0
			self.scroll_area_y1=y1
	def scroll_line_right(self,y,x,n=1):
		if x<self.w:
			n=min(self.w-self.cx,n)
			self.poke(y,x+n,self.peek(y,x,y+1,self.w-n))
			self.clear(y,x,y+1,x+n)
	def scroll_line_left(self,y,x,n=1):
		if x<self.w:
			n=min(self.w-self.cx,n)
			self.poke(y,x,self.peek(y,x+n,y+1,self.w))
			self.clear(y,self.w-n,y+1,self.w)

	# Cursor functions
	def cursor_line_width(self,next_char):
		wx=self.utf8_charwidth(next_char)
		cx=0
		for x in range(min(self.cx,self.w)):
			char=self.peek(self.cy,x,self.cy+1,x+1)[0]&0xffff
			wx+=self.utf8_charwidth(char)
		return wx,cx
	def cursor_up(self,n=1):
		self.cy=max(self.scroll_area_y0,self.cy-n)
	def cursor_down(self,n=1):
		self.cy=min(self.scroll_area_y1-1,self.cy+n)
	def cursor_left(self,n=1):
		self.cx=max(0,self.cx-n)
	def cursor_right(self,n=1):
		self.cx=min(self.w-1,self.cx+n)
	def cursor_set_x(self,x):
		self.cx=max(0,x)
	def cursor_set_y(self,y):
		self.cy=max(0,min(self.h-1,y))
	def cursor_set(self,y,x):
		self.cursor_set_x(x)
		self.cursor_set_y(y)
	
	# Dumb terminal
	def ctrl_BS(self):
		delta_y,cx=divmod(self.cx-1,self.w)
		cy=max(self.scroll_area_y0,self.cy+delta_y)
		self.cursor_set(cy,cx)
	def ctrl_HT(self,n=1):
		if n>0 and self.cx>=self.w:
			return
		if n<=0 and self.cx==0:
			return
		ts=0
		for i in range(len(self.tab_stops)):
			if self.cx>=self.tab_stops[i]:
				ts=i
		ts+=n
		if ts<len(self.tab_stops) and ts>=0:
			self.cursor_set_x(self.tab_stops[ts])
		else:
			self.cursor_set_x(self.w-1)
	def ctrl_LF(self):
		if self.vt100_mode_lfnewline:
			ctrl_CR()
		if self.cy==self.scroll_area_y1-1:
			self.scroll_area_up(self.scroll_area_y0,self.scroll_area_y1)
		else:
			self.cursor_down()
	def ctrl_CR(self):
		self.cursor_set_x(0)
	def dumb_write(self,char):
		if char==8:
			self.ctrl_BS()
		elif char==9:
			self.ctrl_HT()
		elif char>=10 and char<=12:
			self.ctrl_LF()
		elif char==13:
			self.ctrl_CR()
	def dumb_echo(self,char):
		# Check right bound
		wx,cx=self.cursor_line_width(char)
		# Newline
		if wx>self.w:
			if self.vt100_mode_autowrap:
				self.ctrl_CR()
				self.ctrl_LF()
			else:
				self.cx=cx
		if self.vt100_mode_insert:
			self.scroll_line_right(self.cy,self.cx)
		self.poke(self.cy,self.cx,array.array('i',[self.attr|char]))
		self.cursor_set_x(self.cx+1)
		
	# VT-100 terminal
	def charset_select(self,G):
		# Select charset
		pass
	def charset_set(self,G,sel):
		# Set charset
		pass
	def esc_DECALN(self):
		# Screen alignment display
		self.fill(0,0,self.h,self.w,0x00fe0045)
	def esc_SCP(self):
		# Store cursor position
		self.vt100_saved_cx=self.cx
		self.vt100_saved_cy=self.cy
		self.vt100_saved_attr=self.attr
		self.vt100_saved_charmap=self.vt100_charmap
		self.vt100_saved_mode_origin=self.vt100_mode_origin
	def esc_RCP(self):
		# Retore cursor position
		self.cx=self.vt100_saved_cx
		self.cy=self.vt100_saved_cy
		self.attr=self.vt100_saved_attr
		self.vt100_charmap=self.vt100_saved_charmap
		self.vt100_mode_origin=self.vt100_saved_mode_origin
	def esc_IND(self):
		self.ctrl_LF()
	def esc_NEL(self):
		# Next line
		self.ctrl_CR()
		self.ctrl_LF()
	def esc_RI(self):
		# Reverse line feed
		if self.cy==self.scroll_area_y0:
			self.scroll_area_down(self.scroll_area_y0,self.scroll_area_y1)
		else:
			self.cursor_up()
	def csi_ICH(self,p):
		# Insert character
		p=self.vt100_parse_params(p,[1])
		self.scroll_line_right(self.cy,self.cx, p[0])
	def csi_CUU(self,p):
		# Cursor up
		p=self.vt100_parse_params(p,[1])
		self.cursor_up(max(1,p[0]))
	def csi_CUD(self,p):
		# Cursor down
		p=self.vt100_parse_params(p,[1])
		self.cursor_down(max(1,p[0]))
	def csi_CUF(self,p):
		# Cursor right
		p=self.vt100_parse_params(p,[1])
		self.cursor_right(max(1,p[0]))
	def csi_CUB(self,p):
		# Cursor left
		p=self.vt100_parse_params(p,[1])
		self.cursor_left(max(1,p[0]))
	def csi_CNL(self,p):
		# Cursor next line
		self.csi_CUD(p)
		self.ctrl_CR()
	def csi_CPL(self,p):
		# Cursor preceding line
		self.csi_CUU(p)
		self.ctrl_CR()
	def csi_CHA(self,p):
		# Cursor character absolute
		p=self.vt100_parse_params(p,[1])
 		self.cursor_set_x(p[0]-1)
	def csi_CUP(self,p):
		# Set cursor position
		p=self.vt100_parse_params(p,[1,1])
		if self.vt100_mode_origin:
			self.cursor_set(self.scroll_area_y0+p[0]-1,p[1]-1)
		else:
			self.cursor_set(p[0]-1,p[1]-1)
	def csi_ED(self,p):
		# Erase in display
		p=self.vt100_parse_params(p,['0'],False)
		if p[0]=='0':
			self.clear(self.cy,self.cx,self.h,self.w)
		elif p[0]=='1':
			self.clear(0,0,self.cy+1,self.cx+1)
		elif p[0]=='2':
			self.clear(0,0,self.h,self.w)
	def csi_EL(self,p):
		# Erase in line
		p=self.vt100_parse_params(p,['0'],False)
		if p[0]=='0':
			self.clear(self.cy,self.cx,self.cy+1,self.w)
		elif p[0]=='1':
			self.clear(self.cy,0,self.cy+1,self.cx+1)
		elif p[0]=='2':
			self.clear(self.cy,0,self.cy+1,self.w)
	def csi_IL(self,p):
		# Insert line
		p=self.vt100_parse_params(p,[1])
		if (self.cy>=self.scroll_area_y0 and self.cy<self.scroll_area_y1):
			self.scroll_area_down(self.cy,self.scroll_area_y1,max(1,p[0]))
	def csi_DL(self,p):
		# Delete line
		p=self.vt100_parse_params(p,[1])
		if (self.cy>=self.scroll_area_y0 and self.cy<self.scroll_area_y1):
			self.scroll_area_up(self.cy,self.scroll_area_y1,max(1,p[0]))	
	def csi_DCH(self,p):
		# Delete characters
		p=self.vt100_parse_params(p,[1])
		self.scroll_line_left(self.cy,self.cx,max(1,p[0]))
	def csi_CTC(self,p):
		# Cursor tabulation control
		p=self.vt100_parse_params(p,['0'],False)
		for m in p:
			if m=='0':
				try:
					ts=self.tab_stops.index(self.cx)
				except ValueError:
					tab_stops=self.tab_stops
					tab_stops.append(self.cx)
					tab_stops.sort()
					self.tab_stops=tab_stops
			elif m=='2':
				try:
					self.tab_stops.remove(self.cx)
				except ValueError:
					pass
			elif m=='5':
				self.tab_stops=[0]
	def csi_ECH(self,p):
		# Erase character
		p=self.vt100_parse_params(p,[1])
		n=min(self.w-self.cx,max(1,p[0]))
		self.clear(self.cy,self.cx,self.cy+1,self.cx+n);
	def csi_CHT(self,p):
		# Cursor forward tabulation
		p=self.vt100_parse_params(p,[1])
		self.ctrl_HT(max(1,p[0]))
	def csi_CBT(self,p):
		# Cursor backward tabulation
		p=self.vt100_parse_params(p,[1])
		self.ctrl_HT(1-max(1,p[0]))
	def csi_HPA(self,p):
		# Character position absolute
		p=self.vt100_parse_params(p,[1])
		self.cursor_set_x(p[0]-1)
	def csi_HPR(self,p):
		# Character position forward
		self.csi_CUF(p)
	def csi_DA(self,p):
		# Device attributes
		p=self.vt100_parse_params(p,['0'],False)
		if p[0]=='0':
			self.vt100_out="\x1b[?1;2c"
		elif p[0]=='>0' or p[0]=='>':
			self.vt100_out="\x1b[>0;184;0c"
	def csi_VPA(self,p):
		# Line position absolute
		p=self.vt100_parse_params(p,[1])
		self.cursor_set_y(p[0]-1)
	def csi_VPR(self,p):
		# Line position forward
		self.csi_CUD(p)
	def csi_HVP(self,p):
		# Character and line position
		self.csi_CUP(p)
	def csi_TBC(self,p):
		# Tabulation clear
		p=self.vt100_parse_params(p,['0'],False)
		if p[0]=='0':
			self.csi_CTC('2')
		elif p[0]=='3':
			self.csi_CTC('5')
	def csi_SM(self,p):
		# Set mode
		p=self.vt100_parse_params(p,[],False)
		for m in p:
			if m=='4':
				# Insertion replacement mode
				self.vt100_mode_insert=True
			elif m=='?3':
				# Column mode
				if self.vt100_mode_column_switch:
					self.w=132
					self.reset()
			elif m=='?5':
				# Screen mode
				self.vt100_mode_inverse=True
			elif m=='?6':
				# Region origin mode
				self.vt100_mode_origin=True
				self.cursor_set(self.scroll_area_y0,0)
			elif m=='?7':
				# Autowrap mode
				self.vt100_mode_autowrap=True
			elif m=='?20':
				# Linefeed/new line mode
				self.vt100_mode_lfnewline=True
			elif m=='?25':
				# Text cursor enable mode
				self.vt100_mode_cursor=True
			elif m=='?40':
				# Column switch control
				self.vt100_mode_column_switch=True
			elif m=='?47':
				# Alternate screen mode
				if not self.vt100_mode_alt_screen:
					self.screen,self.screen2=self.screen2,self.screen
				self.vt100_mode_alt_screen=True
	def csi_RM(self,p):
		# Reset mode
		p=self.vt100_parse_params(p,[],False)
		for m in p:
			if m=='4':
				# Insertion replacement mode
				self.vt100_mode_insert=False
			elif m=='?3':
				# Column mode
				if self.vt100_mode_column_switch:
					self.w=80
					self.reset()
			elif m=='?5':
				# Screen mode
				self.vt100_mode_inverse=False
			elif m=='?6':
				# Region origin mode
				self.vt100_mode_origin=False
				self.cursor_set(0,0)
			elif m=='?7':
				# Autowrap mode
				self.vt100_mode_autowrap=False
			elif m=='?20':
				# Linefeed/new line mode
				self.vt100_mode_lfnewline=False
			elif m=='?25':
				# Text cursor enable mode
				self.vt100_mode_cursor=False
			elif m=='?40':
				# Column switch control
				self.vt100_mode_column_switch=False
			elif m=='?47':
				# Alternate screen mode
				if self.vt100_mode_alt_screen:
					self.screen,self.screen2=self.screen2,self.screen
				self.vt100_mode_alt_screen=False
	def csi_SGR(self,p):
		# Select graphic rendition
		p=self.vt100_parse_params(p,[0])
		for m in p:
			if m==0:
				# Reset
				self.attr=0x00fe0000
			elif m==4:
				# Underlined
				self.attr|=0x01000000
			elif m==7:
				# Negative
				self.attr|=0x02000000
			elif m==8:
				# Concealed
				self.attr|=0x04000000
			elif m==24:
				# Not underlined
				self.attr&=0x7eff0000
			elif m==27:
				# Positive
				self.attr&=0x7dff0000
			elif m==28:
				# Revealed
				self.attr&=0x7bff0000
			elif m>=30 and m<=37:
				# Foreground
				self.attr=(self.attr&0x7f0f0000)|((m-30)<<20)
			elif m==39:
				# Default fg color
				self.attr=(self.attr&0x7f0f0000)|0x00f00000
			elif m>=40 and m<=47:
				# Background
				self.attr=(self.attr&0x7ff00000)|((m-40)<<16)
			elif m==49:
				# Default bg coor
				self.attr=(self.attr&0x7ff00000)|0x000e0000
	def csi_DSR(self,p):
		# Device status report
		p=self.vt100_parse_params(p,['0'],False)
		if p[0]=='5':
			self.vt100_out="\x1b[0n"
		elif p[0]=='6':
			x=self.cx+1
			y=self.cy+1
			self.vt100_out='\x1b[%d;%dR'%(y,x)	
		elif p[0]=='7':
			self.vt100_out="WebShell"
		elif p[0]=='8':
			self.vt100_out=version
	def csi_DECSTBM(self,p):
		# Set top and bottom margins
		p=self.vt100_parse_params(p,[1,self.h])
		self.scroll_area_set(p[0]-1,p[1])
		if self.vt100_mode_origin:
			self.cursor_set(self.scroll_area_y0,0)
		else:
			self.cursor_set(0,0)
	def csi_DECREQTPARM(self,p):
		# Request terminal parameters
		p=self.vt100_parse_params(p,[],False)
		if p[0]=='0':
			self.vt100_out="\x1b[2;1;1;112;112;1;0x"
		elif p[0]=='1':
			self.vt100_out="\x1b[3;1;1;112;112;1;0x"
	def vt100_parse_params(self,p,d,to_int=True):
		# Process parameters (params p with defaults d)
		prefix=''
		if len(p)>0:
			if p[0]>='<' and p[0]<='?':
				prefix=p[0]
				p=p[1:]
			p=p.split(';')
		else:
			p=''
		n=max(len(p),len(d))
		o=[]
		for i in range(n):
			value_def=False
			if i<len(p):
				value=prefix+p[i]
				value_def=True
				if to_int:
					try:
						value=int(value)
					except ValueError:
						value_def=False
			if (not value_def) and i<len(d):
				value=d[i]
			o.append(value)
		return o
	def vt100_parse_reset(self,vt100_parse_state="",vt100_parse_len=0):
		self.vt100_parse_len=vt100_parse_len
		self.vt100_parse_state=vt100_parse_state
		self.vt100_parse_func=""
		self.vt100_parse_param=""
		return True
	def vt100_process(self):
		if self.vt100_parse_state=='esc':
			# ESC mode
			f=self.vt100_parse_func
#			if f!='[':
#				print 'ESC code: ',f
			if f=='[':
				return self.vt100_parse_reset('csi',1)
			elif f=='#8':
				self.esc_DECALN()
			elif f=='(A':
				self.charset_set(1,0)
			elif f=='(B':
				self.charset_set(1,1)
			elif f=='(0':
				self.charset_set(1,2)
			elif f=='(1':
				self.charset_set(1,3)
			elif f=='(2':
				self.charset_set(1,4)
			elif f==')A':
				self.charset_set(0,0)
			elif f==')B':
				self.charset_set(0,1)
			elif f==')0':
				self.charset_set(0,2)
			elif f==')1':
				self.charset_set(0,3)
			elif f==')2':
				self.charset_set(0,4)
			elif f=='7':
				self.esc_SCP()
			elif f=='8':
				self.esc_RCP()
			elif f=='D':
				self.esc_IND()
			elif f=='E':
				self.esc_NEL()
			elif f=='H':
				self.csi_CTC('0')
			elif f=='M':
				self.esc_RI()
			elif f=='N':
				self.esc_SS2()
			elif f=='O':
				self.esc_SS3()
			elif f=='Z':
				self.csi_DA('0')
			elif f=='c':
				self.reset_hard()
		else:
			# CSI mode
			f=self.vt100_parse_func
			p=self.vt100_parse_param
#			print 'CSI code: ',p,f
			if f=='@':
				self.csi_ICH(p)
			elif f=='A':
				self.csi_CUU(p)
			elif f=='B':
				self.csi_CUD(p)
			elif f=='C':
				self.csi_CUF(p)
			elif f=='D':
				self.csi_CUB(p)
			elif f=='E':
				self.csi_CNL(p)
			elif f=='F':
				self.csi_CPL(p)
			elif f=='G':
				self.csi_CHA(p)
			elif f=='H':
				self.csi_CUP(p)
			elif f=='I':
				self.csi_CHT(p)
			elif f=='J':
				self.csi_ED(p)
			elif f=='K':
				self.csi_EL(p)
			elif f=='L':
				self.csi_IL(p)
			elif f=='M':
				self.csi_DL(p)
			elif f=='P':
				self.csi_DCH(p)
			elif f=='W':
				self.csi_CTC(p)
			elif f=='X':
				self.csi_ECH(p)
			elif f=='Z':
				self.csi_CBT(p)
			elif f=='`':
				self.csi_HPA(p)
			elif f=='a':
				self.csi_HPR(p)
			elif f=='c':
				self.csi_DA(p)
			elif f=='d':
				self.csi_VPA(p)
			elif f=='e':
				self.csi_VPR(p)
			elif f=='f':
				self.csi_HVP(p)
			elif f=='g':
				self.csi_TBC(p)
			elif f=='h':
				self.csi_SM(p)
			elif f=='l':
				self.csi_RM(p)
			elif f=='m':
				self.csi_SGR(p)
			elif f=='n':
				self.csi_DSR(p)
			elif f=='r':
				self.csi_DECSTBM(p)
			elif f=='s':
				self.esc_SCP()
			elif f=='u':
				self.esc_RCP()
			elif f=='x':
				self.csi_DECREQTPARM(p)
#			else:
#				print 'Unknown'
		return self.vt100_parse_reset()
	def vt100_write(self,char):
		if char<32:
			if char==27:
				self.vt100_parse_reset('esc')
			elif char==24 or char==26:
				self.vt100_parse_reset('')
			else:
				return False
		elif char>=0x80 and char<=0x9f:
			self.vt100_parse_reset('esc')
			self.vt100_parse_func=chr(char-0x40)
			self.vt100_process()
		elif self.vt100_parse_state:
			self.vt100_parse_len+=1
			if self.vt100_parse_len>32:
				self.vt100_parse_reset()
			char_msb=char&0xf0
			if char_msb<0x20:
				pass
			elif char_msb==0x20:
				# Intermediate bytes (added to function)
				self.vt100_parse_func+=unichr(char)
			elif char_msb==0x30 and self.vt100_parse_state=='csi':
				# Parameter byte
				self.vt100_parse_param+=unichr(char)
			else:
				# Function byte
				self.vt100_parse_func+=unichr(char)
				self.vt100_process()
		else:
			return False
		return True

	# External interface
	def set_size(self,w,h):
#		if w<2 or w>256 or h<2 or h>256:
#			return False
#		self.w=w
#		self.h=h
#		reset()
		return True
	def read(self):
		d=self.vt100_out
		self.vt100_out=""
		return d
	def write(self,d):
		d=self.utf8_decode(d)
		for c in d:
			char=ord(c)
			if not self.vt100_write(char):
				if char<32:
					self.dumb_write(char)
				elif char<=0xffff:
					self.dumb_echo(char)
		return True
	def dump(self):
		pre=u""
		attr_=-1
		cx,cy=min(self.cx,self.w-1),self.cy
		for y in range(0,self.h):
			wx=0
			for x in range(0,self.w):
				d=self.screen[y*self.w+x]
				char=d&0xffff
				attr=d>>16
				# Cursor
				if cy==y and cx==x and self.vt100_mode_cursor:
					attr=attr&0xfff0|0x000c
				# Attributes
				if attr!=attr_:
					if attr_!=-1:
						pre+=u'</span>'
					bg=attr&0x000f
					fg=(attr&0x00f0)>>4
					inv=attr&0x0200
					inv2=self.vt100_mode_inverse
					if (inv and not inv2) or (inv2 and not inv):
						fg,bg=bg,fg
					if attr&0x0400:
						fg=0xc
					if attr&0x0100:
						ul=' ul'
					else:
						ul=''
					pre+=u'<span class="f%x b%x%s">'%(fg,bg,ul)
					attr_=attr
				# Escape HTML characters
				if char==38:
					pre+='&amp;'
				elif char==60:
					pre+='&lt;'
				elif char==62:
					pre+='&gt;'
				else:
					wx+=self.utf8_charwidth(char)
					if wx<=self.w:
						pre+=unichr(char)
			pre+="\n"
		# Encode in UTF-8
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
			w,h=self.session[sid]['w'],self.session[sid]['h']
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
				ls=os.environ['LANG'].split('.')
			except KeyError:
				ls=[]
			if len(ls)<2:
				ls=['en_US','UTF-8']
			try:
				os.putenv('COLUMNS',str(w))
				os.putenv('LINES',str(h))
				os.putenv('TERM','linux')
				os.putenv('PATH',os.environ['PATH'])
				os.putenv('LANG',ls[0]+'.UTF-8')
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
			# Process management
			now=time.time()
			fds=[]
			fd2sid={}
			for sid in self.session.keys():
				then=self.session[sid]['time']
				if (now-then)>120:
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
		for i in ['css','html','js','png','jpg']:
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
