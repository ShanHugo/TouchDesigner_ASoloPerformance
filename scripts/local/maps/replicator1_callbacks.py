# me - this DAT
# 
# comp - the replicator component which is cooking
# allOps - a list of all replicants, created or existing
# newOps - the subset that were just created
# template - table DAT specifying the replicator attributes
# master - the master operator
#

def replicate(comp, allOps, newOps, template, master):

	for c in newOps:
		#c.display = True
		#c.render = True
		#c.par.display = 1
		#c.par.clone = comp.par.master
	
		c.par.clone.expr = "op('../midi/device')[me.digits, 'definition'] + '/mapmaster1'"

		pass

	return
