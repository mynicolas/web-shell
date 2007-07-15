webshell={};
webshell.TerminalClass=function(id,width,height) {
	var ie=0;
	if(window.ActiveXObject)
		ie=1;
	var sid=""+Math.round(Math.random()*1000000000);
	var query0="s="+sid+"&w="+width+"&h="+height;
	var query1=query0+"&k=";
	var buf="";
	var timeout;
	var error_timeout;
	var keybuf=[];
	var sending=0;
	var rmax=1;

	var div=document.getElementById(id);
	var dterm=document.createElement('div');

	var opt_get=true;

	function mozilla_clipboard() {
		 // mozilla sucks
		try {
			netscape.security.PrivilegeManager.enablePrivilege("UniversalXPConnect");
		} catch (err) {
			debug('Access denied, <a href="http://kb.mozillazine.org/Granting_JavaScript_access_to_the_clipboard" target="_blank">more info</a>');
			return undefined;
		}
		var clip = Components.classes["@mozilla.org/widget/clipboard;1"].createInstance(Components.interfaces.nsIClipboard);
		var trans = Components.classes["@mozilla.org/widget/transferable;1"].createInstance(Components.interfaces.nsITransferable);
		if (!clip || !trans)
			return undefined;
		trans.addDataFlavor("text/unicode");
		clip.getData(trans,clip.kGlobalClipboard);
		var str=new Object();
		var strLength=new Object();
		try {
			trans.getTransferData("text/unicode",str,strLength);
		} catch(err) {
			return "";
		}
		if (str)
			str=str.value.QueryInterface(Components.interfaces.nsISupportsString);
		if (str)
			return str.data.substring(0,strLength.value / 2);
		else
			return "";
	}
	function do_paste(event) {
		var p=undefined;
		if (window.clipboardData)
			p=window.clipboardData.getData("Text");
		else if(window.netscape)
			p=mozilla_clipboard();
		if (p)
			queue(encodeURIComponent(p));
	}
	function update() {
		if(sending==0) {
			sending=1;
			var r=new XMLHttpRequest();
			var send="";
			while(keybuf.length>0)
				send+=keybuf.pop();
			var query=query1+send;
			if(opt_get) {
				r.open("GET","u?"+query,true);
				if(ie)
					r.setRequestHeader("If-Modified-Since", "Sat, 1 Jan 2000 00:00:00 GMT");
			} else
				r.open("POST","u",true);
			r.setRequestHeader('Content-Type','application/x-www-form-urlencoded');
			r.onreadystatechange = function () {
				if (r.readyState==4) {
					if(r.status==200) {
						window.clearTimeout(error_timeout);
						de=r.responseXML.documentElement;
						if(de.tagName=="pre") {
							Sarissa.updateContentFromNode(de, dterm);
							rmax=100;
						} else {
							rmax*=2;
							if(rmax>2000)
								rmax=2000;
						}
						sending=0;
						timeout=window.setTimeout(update,rmax);
					} else
						debug("Connection error.");
				}
			}
//			error_timeout=window.setTimeout(error,5000);
			if (opt_get)
				r.send(null);
			else
				r.send(query);
		}
	}
	function queue(s) {
		keybuf.unshift(s);
		if(sending==0) {
			window.clearTimeout(timeout);
			timeout=window.setTimeout(update,1);
		}
	}
	this.sendkey = function(kc) {
		private_sendkey(kc);
	}
	function private_sendkey(kc) {
		var k="";

		// Build character
		switch (kc) {
		case 63276: k="[5~"; break;		// PgUp
		case 63277: k="[6~"; break;		// PgDn
		case 63275: k="[4~"; break;		// End
		case 63273: k="[1~"; break;		// Home
		case 63234: k="[D"; break;		// Left
		case 63232: k="[A"; break;		// Up
		case 63235: k="[C"; break;		// Right
		case 63233: k="[B"; break;		// Down
		case 63302: k="[2~"; break;		// Ins
		case 63272: k="[3~"; break;		// Del
		case 63236: k="[[A"; break;		// F1
		case 63237: k="[[B"; break;		// F2
		case 63238: k="[[C"; break;		// F3
		case 63239: k="[[D"; break;		// F4
		case 63240: k="[[E"; break;		// F5
		case 63241: k="[17~"; break;	// F6
		case 63242: k="[18~"; break;	// F7
		case 63243: k="[19~"; break;	// F8
		case 63244: k="[20~"; break;	// F9
		case 63245: k="[21~"; break;	// F10
		case 63246: k="[23~"; break;	// F11
		case 63247: k="[24~"; break;	// F12
		}
		if (k.length)
			k=String.fromCharCode(27)+k;
		else {
			if (kc==8)	// Backspace
				kc=127;
			if (kc>=0)
				k=String.fromCharCode(kc);
		}
		
		if(k.length)
			queue(encodeURIComponent(k));
	};
	this.keypress = function(ev) {
		if (!ev) var ev=window.event;
		var kc;

		// Translate other browsers to standard keycodes
		if (ev.keyCode)
			kc=ev.keyCode;
		if (ev.which)
			kc=ev.which;

		if (ev.ctrlKey) {
			if (kc>=0 && kc<=32) kc=kc;
			else if (kc>=65 && kc<=90) kc-=64;
			else if (kc>=97 && kc<=122) kc-=96;
			else {
				switch (kc) {
				case 54: kc=30; break;	// Ctrl-^
				case 109: kc=31; break;	// Ctrl-_
				case 219: kc=27; break;	// Ctrl-[
				case 220: kc=28; break;	// Ctrl-\
				case 221: kc=29; break;	// Ctrl-]
				default: kc=-1; break;  // Invalid
				}
			}
		} else if (ev.which==0) {
			switch(kc) {
			case 8: kc=127; break;		// Backspace
			case 27: break;				// ESC
			case 33: kc=63276; break;	// PgUp
			case 34: kc=63277; break;	// PgDn
			case 35: kc=63275; break;	// End
			case 36: kc=63273; break;	// Home
			case 37: kc=63234; break;	// Left
			case 38: kc=63232; break;	// Up
			case 39: kc=63235; break;	// Right
			case 40: kc=63233; break;	// Down
			case 45: kc=63302; break;	// Ins
			case 46: kc=63272; break;	// Del
			case 112: kc=63236; break;	// F1
			case 113: kc=63237; break;	// F2
			case 114: kc=63238; break;	// F3
			case 115: kc=63239; break;	// F4
			case 116: kc=63240; break;	// F5
			case 117: kc=63241; break;	// F6
			case 118: kc=63242; break;	// F7
			case 119: kc=63243; break;	// F8
			case 120: kc=63244; break;	// F9
			case 121: kc=63245; break;	// F10
			case 122: kc=63246; break;	// F11
			case 123: kc=63247; break;	// F12
			default: kc=-1; break;		// Invalid
			}
		}

		if (kc >= 0) {
			private_sendkey(kc);
			
			ev.cancelBubble=true;
			if (ev.stopPropagation) ev.stopPropagation();
			if (ev.preventDefault) ev.preventDefault();
		}

		return true;
	}
	this.keydown = function(ev) {
		if (!ev) var ev=window.event;
		if (ie) {
			o={9:1,8:1,27:1,33:1,34:1,35:1,36:1,37:1,38:1,39:1,40:1,45:1,46:1,112:1,
			113:1,114:1,115:1,116:1,117:1,118:1,119:1,120:1,121:1,122:1,123:1};
			if (o[ev.keyCode] || ev.ctrlKey || ev.altKey) {
				ev.which=0;
				return keypress(ev);
			}
		}
	}
	function init() {
		div.appendChild(dterm);
		timeout=window.setTimeout(update,100);
	}
	init();
}
webshell.Terminal=function(id,width,height) {
	return new this.TerminalClass(id,width,height);
}
