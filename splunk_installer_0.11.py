#!/usr/bin/env python
# -*- coding: latin-1 -*-

# apt-get install python-pip
# pip install fabric
# fab -P <command>
#
# created by Tim Arneaud - 2014
# all moral rights reserved
#
# This script is awesomely alpha; much functionality and efficiency 
# needs to be added to make this operation completely seamless and 
# compatible with multiple Splunk Architectures
# - e.g. having multiple roles (Searchead/Deployment Server...) installed on the same host.
#
# *- Host ssh credentials are yet to be dynamically enabled and must be added to the script manually
# *- 
#
# Target hosts input is performed via a colon-delimited list - each host on a separate line - hostnames *must* contain the keywords for splunk role. 
# This hostname is not DNS dependent.
# e.g. 
# splunk-indexer-0:192.168.1.100
# splunk-deployment-2:192.168.1.104
#
# execution is performed like the following example:
# %python netfab.py -hl examlist-basic --splunk splunk-5.0.6-185560-Linux-x86_64.tgz -sf splunkforwarder-5.0.6-185560-Linux-x86_64.tgz -sp authorized_keys --deploytask 
#
# Host ssh credentials are yet to be dynamically enabled and 
# must be added to the script manually

from fabric.api import *
from fabric.operations import run, put
from fabric.colors import *
from fabric.state import *
from fabric.contrib.files import *

import argparse
import re, os, sys, time
from multiprocessing import Lock, Process, Queue, current_process
import StringIO
import string
import random



authorized_keys = '''
ssh-rsa <fake key previously put here>
'''

serverclass = ('''
[global]

blacklist.0 = *
stateOnClient = enabled
restartSplunkd = true

[serverClass:forwarder]
filterType = whitelist
whitelist.0 = *-forwarder-*

[serverClass:forwarder:app:inputsapp]
''')

outputs = ('''
[tcpout]
defaultGroup = clonegroup

[tcpout:clonegroup]
server = {listeners}	
''')


#### Fabric Options ####
env.user = 'ubuntu'
#env.password = 'splunk'
env.key_filename = '.ssh/amazon_splunk.pem'
env.parallel = True
env.warn_only = True

cluster_dict = {}
deployment_dict = {}
forwarder_dict = {}
indexer_dict = {}
search_head_dict = {}
cluster = re.compile(r'^.*(-cluster-).*')
deployment = re.compile(r'^.*(-deployment-).*')
forwarder = re.compile(r'^.*(-forwarder-).*')
indexer = re.compile(r'^.*(-indexer-).*')
search_head = re.compile(r'^.*(-search-head-).*')

secret = ''.join(random.choice(string.letters + string.digits) for x in range(20))
clustermaster = ""
cluster_ip_list = ""         
deployserver = ""
deployment_ip_list = ""                 
forwarder_ip_list = ""
indexer_ip_list = ""
search_head_ip_list = ""



command = 'hostname'
splunkfilename = ''
splunkforwarderfilename = ''

def options() :
        parser = argparse.ArgumentParser(description="Splunk à la boom, boom...")
        parser.add_argument('-sc', '--splunk', help='Splunk installation source tgz file', required=False)
        parser.add_argument('-sf', '--splunkforwarder', help='Splunk Forwarder installation source tgz file', required=False)
        parser.add_argument('-hl', '--hostlist', help='Text file containing single line entries of Splunk hosts. Formatted name:ipaddr => e.g. splunk-indexer-0:192.168.0.100', required=True)
        #parser.add_argument('-v', '--verbose', help='Verbose output values:(0,1) - for enabling or disabling output for debugging', required=False)
        parser.add_argument('-inst', '--installtask', action='store_true', help='Invoke the clean and installer tasks for a "Fresher Splunk!"', required=False)
        parser.add_argument('-ct', '--clustertask', action='store_true', help='Invoke the cluster task for Cluster Indexing', required=False)
        parser.add_argument('-dt', '--deploytask', action='store_true', help='Invoke the deployment server task for Deployment setup', required=False)
#        parser.add_argument('-ft', '--forwardertask', action='store_true', help='Invoke the forwarder task for Forwarder setup', required=False)
        parser.add_argument('-it', '--indexertask', action='store_true', help='Invoke the indexer task for Indexer setup', required=False)
        parser.add_argument('-st', '--searchheadtask', action='store_true', help='Invoke the search head task for Search Head setup', required=False)
        args = parser.parse_args()
        splunkfilename = str(args.splunk)
        splunkforwarderfilename = str(args.splunkforwarder)
	hostlist = str(args.hostlist)
	installtask = str(args.installtask)
	clustertask = str(args.clustertask)
	deploytask = str(args.deploytask)
#	forwardertask = str(args.forwardertask)
	forwardertask = ""
	indexertask = str(args.indexertask)
	searchheadtask = str(args.searchheadtask)
	return (splunkfilename,splunkforwarderfilename,hostlist,clustertask,deploytask,forwardertask,indexertask,searchheadtask)

output['running'] = True
output['stdout'] = True
output['stderr'] = True


def splunk_network(hostlist) :
	target_list = open(hostlist,"r")
	for line in target_list :
        	if (cluster.search(line)) :
               		cluster_dict[line.split(':')[0]] = line.split(':')[1].strip()
	        if (deployment.search(line)) :
        	        deployment_dict[line.split(':')[0]] = line.split(':')[1].strip()
	        if (forwarder.search(line)) :
        	        forwarder_dict[line.split(':')[0]] = line.split(':')[1].strip()
        	if (indexer.search(line)) :
                	indexer_dict[line.split(':')[0]] = line.split(':')[1].strip()
	        if (search_head.search(line)) :
        	        search_head_dict[line.split(':')[0]] = line.split(':')[1].strip()
	return (cluster_dict,deployment_dict,forwarder_dict,indexer_dict,search_head_dict)

def splunk_fwdver(splunkforwarderfilename) :
        src_tfile = splunkforwarderfilename		# e.g.  splunkforwarder-5.0.5-179365-Linux-x86_64.tgz
        src_tfile_split = src_tfile.split('-')  	# [splunkforwarder', '5.0.5', '179365', 'Linux', 'x86_64.tgz']
        splunk_type = str(src_tfile_split[0])           # splunk or splunkforwarder)
        splunk_version = str(src_tfile_split[1])        # e.g. 5.0.5 or 6.0
        splunk_revision = str(src_tfile_split[2])       # e.g. 179365
        splunk_os = str(src_tfile_split[3])		# e.g. Linux
	splunk_arch = str((src_tfile_split[4].split('.')[0])) # e.g. x86_64
        splunk_root = str('/opt')                       # e.g. /opt
        splunk_home = splunk_root+'/'+splunk_type       # e.g. /opt/splunkforwarder
	splunkurl = 'http://www.splunk.com/page/download_track?file=%s/universalforwarder/linux/%s&ac=&wget=true&name=wget&platform=%s&architecture=%s&version=%s&product=splunkd&typed=release' % (splunk_version,src_tfile,splunk_os,splunk_arch,splunk_version)
        return (src_tfile,splunk_type,splunk_version,splunk_arch,splunk_root,splunk_home,splunkurl)

def splunk_ver(splunkfilename) :
        src_tfile = splunkfilename			# e.g.  splunk-5.0.5-179365-Linux-x86_64.tgz
        src_tfile_split = src_tfile.split('-')		# [splunk', '5.0.5', '179365', 'Linux', 'x86_64.tgz']
        splunk_type = str(src_tfile_split[0])           # splunk or splunkforwarder)
        splunk_version = str(src_tfile_split[1])        # e.g. 5.0.5 or 6.0
        splunk_revision = str(src_tfile_split[2])       # e.g. 179365
        splunk_os = str(src_tfile_split[3])		# e.g. Linux
	splunk_arch = str((src_tfile_split[4].split('.')[0])) # e.g. x86_64
        splunk_root = str('/opt')                       # e.g. /opt
        splunk_home = splunk_root+'/'+splunk_type       # e.g. /opt/splunk
	splunkurl = 'http://www.splunk.com/page/download_track?file=%s/splunk/linux/%s&ac=&wget=true&name=wget&platform=%s&architecture=%s&version=%s&product=splunkd&typed=release' % (splunk_version,src_tfile,splunk_os,splunk_arch,splunk_version)
        return (src_tfile,splunk_type,splunk_version,splunk_arch,splunk_root,splunk_home,splunkurl)

def splunk_install(desc,ip,host_list,splunkfilename,splunkforwarderfilename,
		clustertask,clustermaster,secret,
		deploytask,deployment_dict,
		forwardertask,forwarder_ip_list,forwarder_dict,
		indexertask,indexer_ip_list,indexer_dict,
		searchheadtask,search_head_ip_list) :
	if (forwarder.search(desc)) :
		src_tfile,splunk_type,splunk_version,splunk_arch,splunk_root,splunk_home,splunkurl = splunk_fwdver(splunkforwarderfilename)
	else :
		src_tfile,splunk_type,splunk_version,splunk_arch,splunk_root,splunk_home,splunkurl = splunk_ver(splunkfilename)
	
	with settings(
	# Choose your verbosity output (this can (should) be dynamic and selectable)
	#hide('warnings'),
	#hide('warnings','running'),
	hide('warnings','running', 'stdout'),
	#hide('warnings','running', 'stdout','stderr'),
	warn_only=True, host_string=ip) : 
		sudo('bash -c \'echo "127.0.0.1\tlocalhost\n" > /etc/hosts\'',shell=False)
		sudo('bash -c \'echo "::1 ip6-localhost\tip6-loopback\n" >> /etc/hosts\'',shell=False)
		for key, value in host_list.items() :
			sudo('bash -c \'echo "%s	%s" >> /etc/hosts\'' %(value, key) ,shell=False)
		
		print(white('Testing Connectivity %s' %(desc) + sudo('uname -vr',shell=False)))
		sudo('killall -9 splunk splunkd python 2>/dev/null',shell=False)
		time.sleep(1)
		sudo(('find %s -name %s | xargs rm -rf 2>/dev/null' % (splunk_root,splunk_type)),shell=False)
		sudo(('rm -rf %s/splunk*' % (splunk_root)),shell=False)
		sudo('/usr/sbin/deluser splunk', shell=False,)
		time.sleep(1)
		print(green('Splunk is purged from %s %s' % (desc,ip)))
		#-----------^^^clean up splunk^^^---------------------------------------------
		print(white('Commencing download of %s to host %s %s:/tmp/%s' % (splunk_type,desc,ip,src_tfile)))
		sudo(('wget --quiet -O /tmp/%s "%s"' %(src_tfile,splunkurl)),shell=False)
		print(white('Download completed to host %s %s' % (desc,ip)))
		sudo(('tar zxf /tmp/%s -C %s' % (src_tfile,splunk_root)),shell=False)
		time.sleep(1)
		sudo(('mv %s/%s %s/%s-%s' % (splunk_root,splunk_type,splunk_root,splunk_type,splunk_version)),shell=False)
		sudo(('ln -s %s/%s-%s %s/%s' % (splunk_root,splunk_type,splunk_version, splunk_root,splunk_type)),shell=False)
		sudo(('useradd -G sudo -m -d %s -s /bin/bash splunk' %(splunk_home)), shell=False)
		sudo('bash -c \'echo "splunk ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/90-cloud-init-users\'', shell=False) 
                sudo(('chown -R splunk:splunk %s/' % (splunk_root)),shell=False)
                sudo(('hostname -b %s' % (desc)),shell=False)
		sudo(('cp /etc/skel/.bashrc %s/.bashrc' % (splunk_home)),shell=False,user='splunk')
		sudo(("sed -i 's/^#force_color_prompt=yes/force_color_prompt=yes/g' %s/.bashrc" %(splunk_home)),shell=False)
		sudo(('cp /etc/skel/.profile %s/.profile' % (splunk_home)),shell=False,user='splunk')
		sudo(('bash -c \'mkdir %s/.ssh && chmod 700 %s/.ssh\'' % (splunk_home,splunk_home)),shell=False,user='splunk')
		sudo(('bash -c \'echo "%s" > %s/.ssh/authorized_keys\'' % (authorized_keys,splunk_home)),shell=False,user='splunk')
		sudo(('chown -R splunk:splunk %s/' % (splunk_home)),shell=False)
		sudo(('%s/bin/splunk start --accept-license' % (splunk_home)),shell=False,user='splunk')
		time.sleep(2)
		sudo(('%s/bin/splunk set servername "%s" -auth admin:changeme' %(splunk_home,desc)),shell=False)
		time.sleep(1)
		sudo(('%s/bin/splunk enable boot-start -user splunk' %(splunk_home)),shell=False)
		sudo(('%s/bin/splunk edit user admin -password splunk -auth admin:changeme' %(splunk_home)),shell=False)
		time.sleep(1)
		print(green("End of Splunk installation for %s" % (desc),bold=True))
		try :
			if (cluster.search(desc)) and clustertask :
				print(white("Cluster conditions matched - starting cluster config"))
				cluster_task(desc,ip,splunk_home,splunk_root,clustermaster,secret,deployment_dict,indexer_ip_list)
		except : pass
		try :
			if (deployment.search(desc)) and deploytask :
				print(white("Deployment conditions matched - starting deployment distribution config"))
				deployment_task(desc,ip,splunk_home,splunk_root,clustermaster,secret,deployment_dict,indexer_ip_list,indexer_dict,forwarder_ip_list,forwarder_dict)
		except : pass

def cluster_task(desc,ip,splunk_home,splunk_root,
		clustermaster,secret,
		deployment_dict,
		indexer_ip_list,indexer_dict) :
	print "Cluster task: " + str(desc + ip + splunkfilename)
        try :
                with settings(parallel = True, host_string=desc) :
			sudo(('%s/bin/splunk edit cluster-config -mode master -replication_factor 3 -search_factor 2 -secret "%s"' %(splunk_home,secret)),shell=False)
			sudo(('%s/bin/splunk restart' % (splunk_home)),shell=False,user='splunk')
			print(cyan('Cluster Master %s %s configured and restarted' %(desc, ip)))
			time.sleep(1)
			clustermaster = desc
			for indxr in indexer_ip_list :
				with settings(parallel = True, host_string=indxr) :
					print(cyan(indxr))
					time.sleep(1)
					print(cyan(sudo(('%s/bin/splunk edit cluster-config -mode slave -master_uri https://%s:8089 -secret "%s" -replication_port 9887' %(splunk_home,clustermaster,secret)),shell=False)))
					sudo(('%s/bin/splunk restart' % (splunk_home)),shell=False,user='splunk')
					print(cyan('Indexer %s is Cluster-configured and restarted' % (indxr)))
					time.sleep(1)
        except Exception as e :
                print str(e)
                pass

def deployment_task(desc,ip,splunk_home,splunk_root,
		clustermaster,secret,
		deployment_dict,
		indexer_ip_list,indexer_dict,
		forwarder_ip_list,forwarder_dict) :
        try :
                with settings(parallel=True, host_string=ip):
			deployserver = desc
			sudo(('bash -c \'echo "%s" > %s/etc/system/local/serverclass.conf\'' % (serverclass,splunk_home)),shell=False)
		
			sudo(('%s/bin/splunk create app inputsapp -template barebones -auth admin:splunk' % (splunk_home)),shell=False)
			sudo(('mv %s/etc/apps/inputsapp %s/etc/deployment-apps/' %(splunk_home, splunk_home)),shell=False)
                	sudo(('chown -R splunk:splunk %s/' % (splunk_root)),shell=False)
			indexer_listeners = ':9997,'.join(map(str,(indexer_ip_list)))+':9997'
			formatted_outputs = outputs.format(listeners = indexer_listeners)
			sudo(('mkdir -p %s/etc/deployment-apps/inputsapp/local' % (splunk_home)),shell=False)
			sudo(('bash -c \'echo "%s" > %s/etc/deployment-apps/inputsapp/local/outputs.conf\'' %(formatted_outputs, splunk_home)),shell=False)
			sudo(('chown -R splunk:splunk %s/' % (splunk_home)),shell=False)
			for desc,ip in indexer_dict.iteritems() :
				splunk_home='/opt/splunk'
				sudo(('%s/bin/splunk add search-server -host %s:8089 -auth admin:splunk -remoteUsername admin -remotePassword splunk' %(splunk_home,desc)),shell=False)
				time.sleep(1)
			sudo(('%s/bin/splunk restart' % (splunk_home)),shell=False,user='splunk')
			print(magenta('Deployment Server %s %s Configured and restarted' %(desc,ip),bold=True))
			for desc,ip in forwarder_dict.iteritems() :
				with settings(parallel = True, host_string=ip) :
					splunk_home='/opt/splunkforwarder'
					sudo(('%s/bin/splunk set deploy-poll %s:8089 -auth admin:splunk' % (splunk_home, deployserver)),shell=False)
					sudo(('%s/bin/splunk enable deploy-client -auth admin:splunk' % (splunk_home)),shell=False)
					sudo(('bash -c \'echo "clientName = %s" >> %s/etc/system/local/deploymentclient.conf\'' % (desc,splunk_home)),shell=False)
					sudo(('%s/bin/splunk restart' % (splunk_home)),shell=False,user='splunk')
					print(blue('Forwarder %s configured for deployments and restarted' % (desc),bold=True))
					time.sleep(2)
			for desc,ip in indexer_dict.iteritems() :
				with settings(parallel = True, host_string=ip) :
					splunk_home='/opt/splunk'
					sudo(('%s/bin/splunk set deploy-poll %s:8089 -auth admin:splunk' % (splunk_home, deployserver)),shell=False)
					sudo(('%s/bin/splunk enable deploy-client -auth admin:splunk' % (splunk_home)),shell=False)
					print(white(sudo(('%s/bin/splunk enable listen 9997 -auth admin:splunk' %(splunk_home)),shell=False)))
					sudo(('%s/bin/splunk restart' % (splunk_home)),shell=False,user='splunk')
					print(yellow('Indexer %s configured for deployments and restarted' % (desc),bold=True))
			time.sleep(2)
			for desc,ip in forwarder_dict.iteritems() :
				with settings(parallel = True, host_string=ip) :
					splunk_home='/opt/splunkforwarder'
					print(blue('Forwarder Check - %s:\n' %(desc) + sudo('%s/bin/splunk list forward-server -auth admin:splunk' %(splunk_home),shell=False)))
					time.sleep(1)
			time.sleep(4)
			splunk_home='/opt/splunk'
			for desc,ip in deployment_dict.iteritems() :
				print(magenta('Deployment Clients Check - %s:\n\t\t ' %(desc) + sudo('%s/bin/splunk list deploy-clients -auth admin:splunk | grep hostname:' %(splunk_home),shell=False)))
				time.sleep(2)
				print(magenta('Search Pool Check - %s:\n' %(desc) + sudo('%s/bin/splunk list search-server -auth admin:splunk' %(splunk_home),shell=False)))
        except Exception as e :
                print str(e)
                pass

def forwarders_task(desc,ip,splunk_home,	# <- currently not utilised - nothing to see here :)
		splunkforwarderfilename,
		clustermaster,secret) :
	pass
        try :
       	        with settings(parallel=True, host_string=ip) :
			pass
        except Exception as e :
       	        print str(e)
      		pass

def indexers_task(desc,ip,splunk_home,		# <- currently not utilised - nothing to see here :)
		splunkfilename,
		clustermaster,secret) :
	try :
		pass
        except Exception as e :
                print str(e)
                pass

def search_head_task(desc,ip,splunk_home,	# <- currently not utilised - nothing to see here :)
		clustermaster,secret) :
        try :
		pass
	except Exception as e :
                print str(e)
                pass

def splunk_healthcheck(desc,ip,splunk_home) :
	try :
                with settings(parallel=True, host_string=ip):
                	try :
                       		if (cluster.search(desc)) and clustertask :
       					print(white("Cluster conditions matched - starting cluster config"))
	                except : pass
        	        try :
                	        if (deployment.search(desc)) and deploytask :
                        	        print(white("Deployment conditions matched - starting deployment distribution config"))
	                except : pass

	except Exception as e :
		print str(e)
		pass

def initiate_connection(desc,ip,host_list,splunkfilename,splunkforwarderfilename,
			clustertask,clustermaster,secret,
			deploytask,deployment_dict,
			forwardertask,forwarder_ip_list,forwarder_dict,
			indexertask,indexer_ip_list,indexer_dict,
			searchheadtask,search_head_ip_list) :
	try :
		splunk_install(desc,ip,host_list,splunkfilename,splunkforwarderfilename,
		clustertask,clustermaster,secret,
		deploytask,deployment_dict,
		forwardertask,forwarder_ip_list,forwarder_dict,
		indexertask,indexer_ip_list,indexer_dict,
		searchheadtask,search_head_ip_list)
	except Exception as e :
		print str(e)
		pass

def worker(work_queue, done_queue) :
	try :
		for desc,ip,host_list,splunkfilename,splunkforwarderfilename,clustertask,clustermaster,secret,deploytask,deployment_dict,forwardertask,forwarder_ip_list,forwarder_dict,indexertask,indexer_ip_list,indexer_dict,searchheadtask,search_head_ip_list in iter(work_queue.get, 'STOP') :
			status_code = initiate_connection(desc,ip,host_list,splunkfilename,splunkforwarderfilename,
			clustertask,clustermaster,secret,
			deploytask,deployment_dict,
			forwardertask,forwarder_ip_list,forwarder_dict,
			indexertask,indexer_ip_list,indexer_dict,
			searchheadtask,search_head_ip_list)
	except Exception as e:
		print str(e)
	return True


def print_splunk(cluster_dict,deployment_dict,forwarder_dict,indexer_dict,search_head_dict) :
        print "\r\n*\t*\t*\t*\t*\t*\t*\t"
        print(white("Splunk deployment is as follows:",bold=True))
        clustermaster = ""
        cluster_ip_list = ""
        deployment_ip_list = ""
        forwarder_ip_list = ""
        indexer_ip_list = ""
        search_head_ip_list = ""
        try :
                if any(cluster_dict.values()[0]):
                        clustermaster =  cluster_dict.values()[0]
                        print(green("\tCluster Server:",bold = True))
			for key,value in cluster_dict.iteritems() :
				print(green('\t' + key + ' ' + value))
        except :
                pass
        try :
                if any(deployment_dict.values()[0]) :
                        print(magenta("\tDeployment Server:",bold=True))
			for key,value in deployment_dict.iteritems() :
				print(magenta('\t' + key + ' ' + value))
        except :
                pass
        try :
                if any(forwarder_dict.values()[0]) :
                        print(blue("\tForwarder Hosts:",bold=True))
			for key,value in forwarder_dict.items() :
				print(blue('\t' + key +' ' + value))
        except :
		pass
        try :
                if any(indexer_dict.values()[0]) :
                        print(yellow("\tIndexer Hosts:",bold=True))
			for key,value in indexer_dict.iteritems() :
				print(yellow('\t' + key + ' ' + value))
        except :
                pass
        try :
                if any(search_head_dict.values()[0]) :
                        print(cyan("\tSearch Head Hosts:"))
			for key,value in search_head_dict.iteritems() :
				print(cyan('\t' + key + ' ' +value))
        except :
                pass
        print "*\t*\t*\t*\t*\t*\t*\r\n"
	return (cluster_ip_list,clustermaster,deployment_ip_list,forwarder_ip_list,indexer_ip_list,search_head_ip_list)

def main() :
	splunkfilename,splunkforwarderfilename,hostlist,clustertask,deploytask,forwardertask,indexertask,searchheadtask = options()
	workers = 11
	work_queue = Queue()
	done_queue = Queue()
	processes = []
	cluster_dict,deployment_dict,forwarder_dict,indexer_dict,search_head_dict = splunk_network(hostlist)
	cluster_ip_list,clustermaster,deployment_ip_list,forwarder_ip_list,indexer_ip_list,search_head_ip_list = print_splunk(cluster_dict,deployment_dict,forwarder_dict,indexer_dict,search_head_dict)
        host_list = {}
        host_list.update(cluster_dict)
        host_list.update(deployment_dict)
        host_list.update(forwarder_dict)
        host_list.update(indexer_dict)
        host_list.update(search_head_dict)
	for key, value in host_list.iteritems() :
		desc = key.strip('\r\n')
		ip = value.strip('\r\n')
		work_queue.put((desc,ip,host_list,splunkfilename,splunkforwarderfilename,
				clustertask,clustermaster,secret,
				deploytask,deployment_dict,
				forwardertask,forwarder_ip_list,forwarder_dict,
				indexertask,indexer_ip_list,indexer_dict,
				searchheadtask,search_head_ip_list))
	
	for w in xrange(workers) :
		p = Process(target=worker, args = (work_queue, done_queue))
		p.start()
		processes.append(p)
		work_queue.put('STOP')
	
	for p in processes :
		p.join()
	
	done_queue.put('STOP')

	for status in iter(done_queue.get, 'STOP') :
		print status


	print_splunk(cluster_dict,deployment_dict,forwarder_dict,indexer_dict,search_head_dict)

if __name__ == '__main__' :
	main()

