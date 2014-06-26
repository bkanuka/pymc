'''
Python module for distributing an MCMC model among Spark clusters. 

It distributes the observation data using Spark's built-in textFile function.
'''

__all__ = ['DistributedMCMC']

from .MCMCSpark import MCMCSpark
from .MCMC import MCMC
from pymc.database import spark

class DistributedMCMC(MCMCSpark):

	def __init__(self, input=None, db='spark', name='MCMC', calc_deviance=True, nJobs=1, **kwargs):
		self.model_function = kwargs.pop("model_function", None)
		self.observation_file = kwargs.pop("observation_file", None)
		self.local_iter = kwargs.pop("local_iter", None)
		self.global_update = kwargs.pop("global_update", None)
		MCMCSpark.__init__(self, input=None, db=db, name=name, calc_deviance=calc_deviance, nJobs=nJobs, **kwargs)

	def sample(
		self, iter, burn=0, thin=1, tune_interval=1000, tune_throughout=True,
		save_interval=None, burn_till_tuned=False, stop_tuning_after=5,
			verbose=0, progress_bar=True):
		name = self.name
		calc_deviance = self.calc_deviance
		kwargs = self.kwargs
		model_function = self.model_function
		observation_file = self.observation_file
		local_iter = self.local_iter
		nJobs = self.nJobs
		global_update = self.global_update

		def sample_on_spark(data):
			def load_ram_database(data_dict):
				from pymc.database import ram
				db = ram.Database('temp_database')
				trace_names = list()
				for key in data_dict.keys():
					if key != '_state_':
						trace_names.append(key)
						db._traces[key] = ram.Trace(name=key, value={0:data_dict[key][-2:-1]}, db=db)
						setattr(db, key, db._traces[key])
					else:
						db._state_ = data_dict[key]
				db.trace_names.append(trace_names)
				return db

			#if isinstance(data, tuple):
			if len(data) == 3:
				input_model = model_function(data[1], phi.value)
				m = MCMC(input_model, db=load_ram_database(data[2]), name=name, calc_deviance=calc_deviance, **kwargs)
			else:
				input_model = model_function(data[1], phi.value)
				m = MCMC(input_model, db='ram', name=name, calc_deviance=calc_deviance, **kwargs)

			m.sample(local_iter, burn, thin, tune_interval, tune_throughout,
        		save_interval, burn_till_tuned, stop_tuning_after,
            	verbose, progress_bar)

			# TODO: Local Update

			#if isinstance(data, tuple):
			if len(data) == 3:
				import numpy as np
				container = data[2]
				for tname in m.db._traces:
					container[tname] = np.concatenate((container[tname],m.trace(tname)[:]))
				container['_state_'] = m.get_state()
				return (data[0], data[1], container)
			else:
				container = {}
				for tname in m.db._traces:
					container[tname] = m.db._traces[tname]._trace[0]
				container['_state_'] = m.get_state()
				return (data[0], data[1], container)

		rdd = self.sc.textFile(observation_file, minPartitions=nJobs).cache().glom().map(lambda x: (int(x[0][0]), x)).cache()
		keys = sorted(rdd.map(lambda x: x[0]).collect())
		d = dict()
		for n, k in enumerate(keys):
			d[k] = n
		rdd = rdd.map(lambda x: (d[x[0]], x[1])).cache()
		current_iter = 0
		while current_iter < iter:
			if self.global_update is not None:
				param = global_update[1]()
				phi = self.sc.broadcast(param)
				# exec(global_update[0] + ' = self.sc.broadcast(param)')
			rdd = rdd.map(sample_on_spark).cache()
			current_iter += self.local_iter
		rdd = rdd.map(lambda x: (x[0], x[2])).cache()
		vars_to_tally = rdd.map(lambda x: x[1].keys()).first()
		vars_to_tally.remove('_state_')
		self._variables_to_tally = set(vars_to_tally)
		self._assign_database_backend(rdd, vars_to_tally)
		if self.save_to_hdfs:
			self.save_as_txt_file(self.dbname)


	def _assign_database_backend(self, db, vars_to_tally):
		'''
		Assign Spark RDD database
		'''
		'''if isinstance(db, str):
			self.db = spark.Database(db, vars_to_tally)
		elif isinstance(db, spark.Database):
			self.db = db
			self.restore_sampler_state()
		else:
			vars_to_tally = rdd.map(lambda x: x[1].keys()).first()
			vars_to_tally.remove('_state_')
			self.db = spark.Database(db, vars_to_tally)
			self.restore_sampler_state()'''
		self.db = spark.Database(db, vars_to_tally)
		