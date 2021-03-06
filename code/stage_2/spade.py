from ops import *
from help import *
import time
from tensorflow.contrib.data import prefetch_to_device, shuffle_and_repeat, map_and_batch
import numpy as np
from vgg19_keras import VGGLoss
from glob import glob
import sys
sys.path.append('../')
from pytorchMetrics import *
from utils import *
import tqdm

os.environ['KMP_DUPLICATE_LIB_OK']='True'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

class spade(object):
    def __init__(self, sess, args):

        self.model_name = 'SPADE_load_test'

        self.sess = sess
        self.checkpoint_dir = args.checkpoint_dir
        self.log_dir = args.log_dir
        self.dataset_name = args.dataset_name
        self.augment_flag = args.augment_flag
        self.result_dir = args.result_dir

        self.epoch = args.epoch
        self.iteration = args.iteration
        self.decay_flag = args.decay_flag
        self.decay_epoch = args.decay_epoch

        self.gan_type = args.gan_type

        self.batch_size = args.batch_size
        self.print_freq = args.print_freq
        self.save_freq = args.save_freq

        self.init_lr = args.lr
        self.TTUR = args.TTUR
        self.ch = args.ch

        self.beta1 = args.beta1
        self.beta2 = args.beta2


        self.num_style = args.num_style
        self.guide_img = args.guide_img


        """ Weight """
        self.adv_weight = args.adv_weight
        self.vgg_weight = args.vgg_weight
        self.feature_weight = args.feature_weight
        self.kl_weight = args.kl_weight

        self.ld = args.ld

        """ Generator """
        self.num_upsampling_layers = args.num_upsampling_layers

        """ Discriminator """
        self.n_dis = args.n_dis
        self.n_scale = args.n_scale
        self.n_critic = args.n_critic
        self.sn = args.sn

        self.img_height = args.img_height
        self.img_width = args.img_width

        self.img_ch = args.img_ch
        self.segmap_ch = args.segmap_ch

        self.gif_dir = os.path.join(args.gif_dir, self.model_dir)
        check_folder(self.gif_dir)
        self.samples_dir = os.path.join(args.samples_dir, self.model_dir)
        check_folder(self.samples_dir)
        self.seed_dir = args.seed_dir

        self.dataset_path = args.dataset_path

        self.metrics_rgb = []
        self.metrics_nir = []


        print()

        print("##### Information #####")
        print("# gan type : ", self.gan_type)
        print("# dataset : ", self.dataset_name)
        print("# batch_size : ", self.batch_size)
        print("# epoch : ", self.epoch)
        print("# iteration per epoch : ", self.iteration)
        print("# TTUR : ", self.TTUR)

        print()

        print("##### Generator #####")
        print("# upsampling_layers : ", self.num_upsampling_layers)

        print()

        print("##### Discriminator #####")
        print("# discriminator layer : ", self.n_dis)
        print("# multi-scale : ", self.n_scale)
        print("# the number of critic : ", self.n_critic)
        print("# spectral normalization : ", self.sn)

        print()

        print("##### Weight #####")
        print("# adv_weight : ", self.adv_weight)
        print("# kl_weight : ", self.kl_weight)
        print("# vgg_weight : ", self.vgg_weight)
        print("# feature_weight : ", self.feature_weight)
        print("# wgan lambda : ", self.ld)
        print("# beta1 : ", self.beta1)
        print("# beta2 : ", self.beta2)

        print()

    ##################################################################################
    # Generator
    ##################################################################################.

    def image_encoder(self, x_init, reuse=False, scope='encoder'):
        channel = self.ch
        with tf.variable_scope(scope, reuse=reuse):
            x = resize_256(x_init)
            x = conv(x, channel, kernel=3, stride=2, pad=1, use_bias=True, sn=self.sn, scope='conv')
            x = instance_norm(x, scope='ins_norm')

            for i in range(3):
                x = lrelu(x, 0.2)
                x = conv(x, channel * 2, kernel=3, stride=2, pad=1, use_bias=True, sn=self.sn, scope='conv_' + str(i))
                x = instance_norm(x, scope='ins_norm_' + str(i))

                channel = channel * 2

                # 128, 256, 512

            x = lrelu(x, 0.2)
            x = conv(x, channel, kernel=3, stride=2, pad=1, use_bias=True, sn=self.sn, scope='conv_3')
            x = instance_norm(x, scope='ins_norm_3')

            if self.img_height >= 256 or self.img_width >= 256 :
                x = lrelu(x, 0.2)
                x = conv(x, channel, kernel=3, stride=2, pad=1, use_bias=True, sn=self.sn, scope='conv_4')
                x = instance_norm(x, scope='ins_norm_4')

            x = lrelu(x, 0.2)

            mean = fully_connected(x, channel // 2, use_bias=True, sn=self.sn, scope='linear_mean')
            var = fully_connected(x, channel // 2, use_bias=True, sn=self.sn, scope='linear_var')
            return mean, var

    def generator(self, segmap, x_mean, x_var, random_style=False, reuse=False, scope="generator"):
        channel = self.ch * 4 * 4
        with tf.variable_scope(scope, reuse=reuse):
            batch_size = segmap.get_shape().as_list()[0]
            if random_style :
                x = tf.random_normal(shape=[batch_size, self.ch * 4])
            else :
                x = z_sample(x_mean, x_var)

            if self.num_upsampling_layers == 'normal':
                num_up_layers = 5
            elif self.num_upsampling_layers == 'more':
                num_up_layers = 6
            elif self.num_upsampling_layers == 'most':
                num_up_layers = 7

            z_width = self.img_width // (pow(2, num_up_layers))
            z_height = self.img_height // (pow(2, num_up_layers))

            """
            # If num_up_layers = 5 (normal)
            
            # 64x64 -> 2
            # 128x128 -> 4
            # 256x256 -> 8
            # 512x512 -> 16
            
            """

            x = fully_connected(x, units=z_height * z_width * channel, use_bias=True, sn=False, scope='linear_x')
            x = tf.reshape(x, [batch_size, z_height, z_width, channel])


            x = spade_resblock(segmap, x, channels=channel, use_bias=True, sn=self.sn, scope='spade_resblock_fix_0')

            x = up_sample(x, scale_factor=2)
            x = spade_resblock(segmap, x, channels=channel, use_bias=True, sn=self.sn, scope='spade_resblock_fix_1')

            if self.num_upsampling_layers == 'more' or self.num_upsampling_layers == 'most':
                x = up_sample(x, scale_factor=2)

            x = spade_resblock(segmap, x, channels=channel, use_bias=True, sn=self.sn, scope='spade_resblock_fix_2')

            for i in range(4) :
                x = up_sample(x, scale_factor=2)
                x = spade_resblock(segmap, x, channels=channel//2, use_bias=True, sn=self.sn, scope='spade_resblock_' + str(i))

                channel = channel // 2
                # 512 -> 256 -> 128 -> 64

            if self.num_upsampling_layers == 'most':
                x = up_sample(x, scale_factor=2)
                x = spade_resblock(segmap, x, channels=channel // 2, use_bias=True, sn=self.sn, scope='spade_resblock_4')

            x = lrelu(x, 0.2)
            x = conv(x, channels=self.img_ch, kernel=3, stride=1, pad=1, use_bias=True, sn=False, scope='logit')
            x = tanh(x)

            return x

    ##################################################################################
    # Discriminator
    ##################################################################################

    def discriminator(self, segmap, x_init, reuse=False, scope="discriminator"):
        D_logit = []
        with tf.variable_scope(scope, reuse=reuse):
            for scale in range(self.n_scale):
                feature_loss = []
                channel = self.ch
                x = tf.concat([segmap, x_init], axis=-1)

                x = conv(x, channel, kernel=4, stride=2, pad=1, use_bias=True, sn=False, scope='ms_' + str(scale) + 'conv_0')
                x = lrelu(x, 0.2)

                feature_loss.append(x)

                for i in range(1, self.n_dis):
                    stride = 1 if i == self.n_dis - 1 else 2

                    x = conv(x, channel * 2, kernel=4, stride=stride, pad=1, use_bias=True, sn=self.sn, scope='ms_' + str(scale) + 'conv_' + str(i))
                    x = instance_norm(x, scope='ms_' + str(scale) + 'ins_norm_' + str(i))
                    x = lrelu(x, 0.2)

                    feature_loss.append(x)

                    channel = min(channel * 2, 512)


                x = conv(x, channels=1, kernel=4, stride=1, pad=1, use_bias=True, sn=self.sn, scope='ms_' + str(scale) + 'D_logit')

                feature_loss.append(x)
                D_logit.append(feature_loss)

                x_init = down_sample_avg(x_init)
                segmap = down_sample_avg(segmap)

            return D_logit

    ##################################################################################
    # Model
    ##################################################################################

    def image_translate(self, segmap_img, x_img=None, random_style=False, reuse=False):

        if random_style :
            x_mean, x_var = None, None
        else :
            x_mean, x_var = self.image_encoder(x_img, reuse=reuse, scope='encoder')

        x = self.generator(segmap_img, x_mean, x_var, random_style, reuse=reuse, scope='generator')

        return x, x_mean, x_var

    def image_discriminate(self, segmap_img, real_img, fake_img):
        real_logit = self.discriminator(segmap_img, real_img, scope='discriminator')
        fake_logit = self.discriminator(segmap_img, fake_img, reuse=True, scope='discriminator')

        return real_logit, fake_logit

    def gradient_penalty(self, real, segmap, fake):
        if self.gan_type == 'dragan':
            shape = tf.shape(real)
            eps = tf.random_uniform(shape=shape, minval=0., maxval=1.)
            x_mean, x_var = tf.nn.moments(real, axes=[0, 1, 2, 3])
            x_std = tf.sqrt(x_var)  # magnitude of noise decides the size of local region
            noise = 0.5 * x_std * eps  # delta in paper

            alpha = tf.random_uniform(shape=[shape[0], 1, 1, 1], minval=-1., maxval=1.)
            interpolated = tf.clip_by_value(real + alpha * noise, -1., 1.)  # x_hat should be in the space of X

        else:
            alpha = tf.random_uniform(shape=[self.batch_size, 1, 1, 1], minval=0., maxval=1.)
            interpolated = alpha * real + (1. - alpha) * fake

        logit = self.discriminator(segmap, interpolated, reuse=True, scope='discriminator')

        GP = []


        for i in range(self.n_scale) :
            grad = tf.gradients(logit[i][-1], interpolated)[0]  # gradient of D(interpolated)
            grad_norm = tf.norm(flatten(grad), axis=1)  # l2 norm

            # WGAN - LP
            if self.gan_type == 'wgan-lp':
                GP.append(self.ld * tf.reduce_mean(tf.square(tf.maximum(0.0, grad_norm - 1.))))

            elif self.gan_type == 'wgan-gp' or self.gan_type == 'dragan':
                GP.append(self.ld * tf.reduce_mean(tf.square(grad_norm - 1.)))

        return tf.reduce_mean(GP)

    def build_model(self):
        self.lr = tf.placeholder(tf.float32, name='learning_rate')

        """ Input Image"""
        self.img_class = Image_data(self.img_height, self.img_width, self.img_ch, self.segmap_ch, self.dataset_path, self.augment_flag)
        self.img_class.preprocess()

        # Create vector with gif images
        self.gif_generator = glob(self.seed_dir + '/mask*.png')
        self.gif_generator.sort(key=lambda f: int(''.join(filter(str.isdigit, f))))


        self.dataset_num = len(self.img_class.image)
        self.test_dataset_num = len(self.img_class.segmap_test)


        img_and_segmap = tf.data.Dataset.from_tensor_slices((self.img_class.image, self.img_class.nir, self.img_class.segmap))
        segmap_test = tf.data.Dataset.from_tensor_slices(self.img_class.segmap_test)


        gpu_device = '/gpu:0'
        img_and_segmap = img_and_segmap.apply(shuffle_and_repeat(self.dataset_num)).apply(
            map_and_batch(self.img_class.image_processing, self.batch_size, num_parallel_batches=16,
                          drop_remainder=True)).apply(prefetch_to_device(gpu_device, self.batch_size))

        segmap_test = segmap_test.apply(shuffle_and_repeat(self.dataset_num)).apply(
            map_and_batch(self.img_class.test_image_processing, batch_size=self.batch_size, num_parallel_batches=16,
                          drop_remainder=True)).apply(prefetch_to_device(gpu_device, self.batch_size))

        img_and_segmap_iterator = img_and_segmap.make_one_shot_iterator()
        segmap_test_iterator = segmap_test.make_one_shot_iterator()

        self.real_x, self.real_x_segmap, self.real_x_segmap_onehot = img_and_segmap_iterator.get_next()
        self.real_x_segmap_test, self.real_x_segmap_test_onehot = segmap_test_iterator.get_next()


        """ Define Generator, Discriminator """
        fake_x, x_mean, x_var = self.image_translate(segmap_img=self.real_x_segmap_onehot, x_img=self.real_x)
        real_logit, fake_logit = self.image_discriminate(segmap_img=self.real_x_segmap_onehot, real_img=self.real_x, fake_img=fake_x)

        if self.gan_type.__contains__('wgan') or self.gan_type == 'dragan':
            GP = self.gradient_penalty(real=self.real_x, segmap=self.real_x_segmap_onehot, fake=fake_x)
        else:
            GP = 0

        """ Define Loss """
        g_adv_loss = self.adv_weight * generator_loss(self.gan_type, fake_logit)
        g_kl_loss = self.kl_weight * kl_loss(x_mean, x_var)
        g_vgg_loss = self.vgg_weight * VGGLoss()(self.real_x, fake_x)
        g_feature_loss = self.feature_weight * feature_loss(real_logit, fake_logit)
        g_reg_loss = regularization_loss('generator') + regularization_loss('encoder')


        d_adv_loss = self.adv_weight * (discriminator_loss(self.gan_type, real_logit, fake_logit) + GP)
        d_reg_loss = regularization_loss('discriminator')

        self.g_loss = g_adv_loss + g_kl_loss + g_vgg_loss + g_feature_loss + g_reg_loss
        self.d_loss = d_adv_loss + d_reg_loss

        """ Result Image """
        self.fake_x = fake_x
        self.random_fake_x, _, _ = self.image_translate(segmap_img=self.real_x_segmap_test_onehot, random_style=True, reuse=True)

        """ Test """
        self.test_segmap_image = tf.placeholder(tf.float32, [1, self.img_height, self.img_width, len(self.img_class.color_value_dict)])
        self.random_test_fake_x, _, _ = self.image_translate(segmap_img=self.test_segmap_image, random_style=True, reuse=True)

        self.test_guide_image = tf.placeholder(tf.float32, [1, self.img_height, self.img_width, self.img_ch])
        self.guide_test_fake_x, _, _ = self.image_translate(segmap_img=self.test_segmap_image, x_img=self.test_guide_image, reuse=True)


        """ Training """
        t_vars = tf.trainable_variables()
        G_vars = [var for var in t_vars if 'encoder' in var.name or 'generator' in var.name]
        D_vars = [var for var in t_vars if 'discriminator' in var.name]

        if self.TTUR :
            beta1 = 0.0
            beta2 = 0.9

            g_lr = self.lr / 2
            d_lr = self.lr * 2

        else :
            beta1 = self.beta1
            beta2 = self.beta2
            g_lr = self.lr
            d_lr = self.lr

        self.G_optim = tf.train.AdamOptimizer(g_lr, beta1=beta1, beta2=beta2).minimize(self.g_loss, var_list=G_vars)
        self.D_optim = tf.train.AdamOptimizer(d_lr, beta1=beta1, beta2=beta2).minimize(self.d_loss, var_list=D_vars)

        """" Summary """
        self.summary_g_loss = tf.summary.scalar("g_loss", self.g_loss)
        self.summary_d_loss = tf.summary.scalar("d_loss", self.d_loss)

        self.summary_g_adv_loss = tf.summary.scalar("g_adv_loss", g_adv_loss)
        self.summary_g_kl_loss = tf.summary.scalar("g_kl_loss", g_kl_loss)
        self.summary_g_vgg_loss = tf.summary.scalar("g_vgg_loss", g_vgg_loss)
        self.summary_g_feature_loss = tf.summary.scalar("g_feature_loss", g_feature_loss)


        g_summary_list = [self.summary_g_loss, self.summary_g_adv_loss, self.summary_g_kl_loss, self.summary_g_vgg_loss, self.summary_g_feature_loss]
        d_summary_list = [self.summary_d_loss]

        self.G_loss = tf.summary.merge(g_summary_list)
        self.D_loss = tf.summary.merge(d_summary_list)

    def train(self):

        # initialize pytorch metrics
        metrics = pytorchMetrics()

        # initialize all variables
        tf.global_variables_initializer().run()

        # saver to save model
        self.saver = tf.train.Saver(max_to_keep=20)

        # summary writer
        self.writer = tf.summary.FileWriter(self.log_dir + '/' + self.model_dir, graph=self.sess.graph, max_queue=1)

        # restore check-point if it exits
        could_load, checkpoint_counter = self.load(self.checkpoint_dir)
        if could_load:
            start_epoch = checkpoint_counter + 1
            batch_id = start_epoch * self.iteration
            print(" [*] Load SUCCESS")
        else:
            start_epoch = 0
            batch_id = 0
            print(" [!] Load failed...")

        # loop for epoch
        start_time = time.time()
        past_g_loss = -1.
        lr = self.init_lr

        for epoch in range(start_epoch, self.epoch):
            if self.decay_flag:
                # lr = self.init_lr * pow(0.5, epoch // self.decay_epoch)
                lr = self.init_lr if epoch < self.decay_epoch else self.init_lr * (self.epoch - epoch) / (self.epoch - self.decay_epoch)
            for batch in range(self.iteration):
                train_feed_dict = {
                    self.lr: lr
                }

                # Update D
                _, d_loss, summary_str = self.sess.run([self.D_optim, self.d_loss, self.D_loss], feed_dict=train_feed_dict)
                self.writer.add_summary(summary_str, batch_id)

                # Update G
                g_loss = None
                if batch_id % self.n_critic == 0:
                    real_x_images, real_x_segmap, fake_x_images, random_fake_x_images, _, g_loss, summary_str = self.sess.run(
                        [self.real_x, self.real_x_segmap, self.fake_x, self.random_fake_x,
                         self.G_optim, self.g_loss, self.G_loss], feed_dict=train_feed_dict)

                    self.writer.add_summary(summary_str, batch_id)
                    past_g_loss = g_loss

                # display training status
                if g_loss == None:
                    g_loss = past_g_loss
                print("\tEpoch: [%4d/%4d] [%5d/%5d] time: %4.4f d_loss: %.8f, g_loss: %.8f" % (
                    epoch+1, self.epoch, batch+1, self.iteration, time.time() - start_time, d_loss, g_loss))

                batch_id += 1

            ######### Run metrics and save model ##########

            # Select true images
            test_samples = 32
            true_rgb, true_nir = self.get_images(type=True, number=test_samples)
            # Select false images
            false_rgb, false_nir = self.get_images(type=False, number=test_samples)

            # Run metrics
            score = metrics.compute_score(true_rgb, false_rgb)
            self.metrics_rgb.append(score)

            score = metrics.compute_score(true_nir, false_nir)
            self.metrics_nir.append(score)

            # Save evaluation summary
            emd = tf.summary.scalar("emd", score.emd)
            fid = tf.summary.scalar("fid", score.fid)
            inception = tf.summary.scalar("inception", score.inception)
            knn = tf.summary.scalar("knn", score.knn)
            mmd = tf.summary.scalar("mmd", score.mmd)
            mode = tf.summary.scalar("mode", score.mode)

            metrics_summary_list = [emd, fid, inception, knn, mmd, mode]
            metrics_ = tf.summary.merge(metrics_summary_list)

            self.writer.add_summary(self.sess.run(metrics_), batch_id)

            # Get images and plot gif file
            rgb_images, nir_images = self.get_gif_images()
            plot_gif(rgb_images, epoch, self.gif_dir, type='rgb')
            plot_gif(nir_images, epoch, self.gif_dir, type='nir')

            # save model for final step
            self.save(self.checkpoint_dir, epoch)

            # Save images separately
            for i, img in enumerate(rgb_images):
                imsave(img, os.path.join(self.samples_dir, 'rgb_%d_%d.png' %(epoch, i)))

            for i, img in enumerate(nir_images):
                imsave(img, os.path.join(self.samples_dir, 'nir_%d_%d.png' %(epoch, i)))

        print("\n\tTraining finished! Saving model and generating gif!")

        # Create gif
        rgb_dataset, _ = load_dataset_list(self.img_class.img_test_dataset_path, type='rgb')
        nir_dataset, _ = load_dataset_list(self.img_class.nir_test_dataset_path, type='nir')
        create_gif(self.gif_dir, self.metrics_rgb, rgb_dataset, type='rgb')
        create_gif(self.gif_dir, self.metrics_nir, nir_dataset, type='nir')

    @property
    def model_dir(self):

        n_dis = str(self.n_scale) + 'multi_' + str(self.n_dis) + 'dis'


        if self.sn:
            sn = '_sn'
        else:
            sn = ''

        if self.TTUR :
            TTUR = '_TTUR'
        else :
            TTUR = ''

	
        return "{}_{}_{}_{}_{}_{}_{}_{}_{}{}{}_{}/".format(self.model_name, self.dataset_name,
                                                                   self.gan_type, n_dis, self.n_critic,
                                                                   self.adv_weight, self.vgg_weight, self.feature_weight,
                                                                   self.kl_weight,
                                                                   sn, TTUR, self.num_upsampling_layers)

    def save(self, checkpoint_dir, step):
        checkpoint_dir = os.path.join(checkpoint_dir, self.model_dir)

        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)

        self.saver.save(self.sess, os.path.join(checkpoint_dir, self.model_name + '.model'), global_step=step)

        # Save pickle
        save([self.metrics_rgb, self.metrics_nir], os.path.join(checkpoint_dir, 'metrics.pkl'))

    def load(self, checkpoint_dir):
        print(" [*] Reading checkpoints...")
        checkpoint_dir = os.path.join(checkpoint_dir, self.model_dir)
        print("checkpoint dir")
        print(checkpoint_dir)

        ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
        if ckpt and ckpt.model_checkpoint_path:
            ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
            self.saver.restore(self.sess, os.path.join(checkpoint_dir, ckpt_name))
            counter = int(ckpt_name.split('-')[-1])

            # Load picle
            [self.metrics_rgb, self.metrics_nir] = load(os.path.join(checkpoint_dir, 'metrics.pkl'))

            print(" [*] Success to read {}".format(ckpt_name))
            return True, counter
        else:
            print(" [!] Failed to find a checkpoint")
            return False, 0

    # Get images, or from dataset, or generated, with random style or not
    def get_images(self, type, number):

        rgb_images = []
        nir_images = []

        for i in range(number):
            # Get true images
            if type == True:
                rgb, nir = merge_images(self.sess.run(self.real_x))

            else:
                rgb, nir = merge_images(self.sess.run(self.random_fake_x))

            rgb_images.append(rgb)
            nir_images.append(nir)

        rgb_images = np.vstack(rgb_images)
        nir_images = np.vstack(nir_images)

        rgb_images = np.rint(postprocessing(rgb_images)).astype(int)
        nir_images = np.rint(postprocessing(nir_images)).astype(int)

        return rgb_images, nir_images

    def get_gif_images(self):

        style_image = load_style_image(self.guide_img, self.img_width, self.img_height, self.img_ch)

        list_rgb_images = []
        list_nir_images = []

        for sample_file in self.gif_generator:
            sample_image = load_segmap(self.dataset_path, sample_file, self.img_width, self.img_height, self.segmap_ch)

            fake_img = self.sess.run(self.guide_test_fake_x, feed_dict={self.test_segmap_image : sample_image, self.test_guide_image : style_image})

            fake_rgb = fake_img[:, :, :, 0:3]
            fake_nir = fake_img[:, :, :, 3]

            list_rgb_images.append(fake_rgb)
            list_nir_images.append(fake_nir)

        list_rgb_images = np.vstack(list_rgb_images)
        list_nir_images = np.vstack(list_nir_images)

        # Convert to the range [0, 255]
        list_rgb_images = np.rint(postprocessing(list_rgb_images)).astype(int)
        list_nir_images = np.rint(postprocessing(list_nir_images)).astype(int)

        return list_rgb_images, list_nir_images

    def guide_test(self):
        tf.global_variables_initializer().run()

        segmap_files = glob(os.path.join(self.dataset_path, 'test/segmap/*.png'))
        style_files = glob(os.path.join(self.dataset_path, 'test/guides/*_rgb.png'))

        self.saver = tf.train.Saver()
        could_load, checkpoint_counter = self.load(self.checkpoint_dir)
        self.result_dir = os.path.join(self.result_dir, self.model_dir, 'guide')
        check_folder(self.result_dir)

        if could_load:
            print(" [*] Load SUCCESS")
        else:
            print(" [!] Load failed...")

        # write html for visual comparison
        index_path = os.path.join(self.result_dir, 'index.html')
        index = open(index_path, 'w')
        index.write("<html><body><table><tr>")
        index.write("<th>name</th><th>style RGB</th><th>style NIR</th><th>input</th><th>output RGB</th><th>output NIR</th></tr>")

        for style in style_files:

            style_image = load_style_image(style[:-8], self.img_width, self.img_height, self.img_ch)

            for sample_file in segmap_files:
                sample_image = load_segmap(self.dataset_path, sample_file, self.img_width, self.img_height, self.segmap_ch)
                image_path = os.path.join(self.result_dir, '{}'.format(os.path.basename(sample_file)[:-4]))

                fake_img = self.sess.run(self.guide_test_fake_x, feed_dict={self.test_segmap_image: sample_image,
                                                                            self.test_guide_image: style_image})

                fake_rgb = np.rint(postprocessing(fake_img[:, :, :, 0:3])).astype(int)[0]
                fake_nir = np.rint(postprocessing(fake_img[:, :, :, 3])).astype(int)[0]

                imsave(fake_rgb, image_path + os.path.basename(style)[:-8] + '_rgb.png')
                imsave(fake_nir, image_path + os.path.basename(style)[:-8] + '_nir.png')

                index.write("<td>%s</td>" % os.path.basename(image_path))
                index.write(
                    "<td><img src='%s' width='%d' height='%d'></td>" % (
                            '../../../../' + style[:-8] + '_rgb.png', self.img_width, self.img_height))
                index.write(
                    "<td><img src='%s' width='%d' height='%d'></td>" % (
                            '../../../../' + style[:-8] + '_nir.png', self.img_width, self.img_height))
                index.write(
                    "<td><img src='%s' width='%d' height='%d'></td>" % (
                            '../../../../' + sample_file, self.img_width, self.img_height))
                index.write(
                    "<td><img src='%s' width='%d' height='%d'></td>" % (
                            '../../../../' + image_path + os.path.basename(style)[:-8] + '_rgb.png', self.img_width, self.img_height))
                index.write(
                    "<td><img src='%s' width='%d' height='%d'></td>" % (
                            '../../../../' + image_path + os.path.basename(style)[:-8] + '_nir.png', self.img_width, self.img_height))
                index.write("</tr>")

        index.close()

        tf.global_variables_initializer().run()

        segmap_files = glob('./dataset/{}/{}/*.*'.format(self.dataset_name, 'segmap_test'))

        self.saver = tf.train.Saver()
        could_load, checkpoint_counter = self.load(self.checkpoint_dir)
        self.result_dir = os.path.join(self.result_dir, self.model_dir)
        check_folder(self.result_dir)

        if could_load:
            print(" [*] Load SUCCESS")
        else:
            print(" [!] Load failed...")

        # write html for visual comparison
        index_path = os.path.join(self.result_dir, 'index.html')
        index = open(index_path, 'w')
        index.write("<html><body><table><tr>")
        index.write("<th>name</th><th>input</th><th>output</th></tr>")

        for sample_file in tqdm(segmap_files):
            sample_image = load_segmap(self.dataset_path, sample_file, self.img_width, self.img_height, self.segmap_ch)
            file_name = os.path.basename(sample_file).split(".")[0]
            file_extension = os.path.basename(sample_file).split(".")[1]

            for i in range(self.num_style):
                image_path = os.path.join(self.result_dir, '{}_style{}.{}'.format(file_name, i, file_extension))

                fake_img = self.sess.run(self.random_test_fake_x, feed_dict={self.test_segmap_image: sample_image})
                save_images(fake_img, [1, 1], image_path)

                index.write("<td>%s</td>" % os.path.basename(image_path))
                index.write(
                    "<td><img src='%s' width='%d' height='%d'></td>" % (sample_file if os.path.isabs(sample_file) else (
                            '../..' + os.path.sep + sample_file), self.img_width, self.img_height))
                index.write(
                    "<td><img src='%s' width='%d' height='%d'></td>" % (image_path if os.path.isabs(image_path) else (
                            '../..' + os.path.sep + image_path), self.img_width, self.img_height))
                index.write("</tr>")

        index.close()

    def load_model(self):
        tf.global_variables_initializer().run()

        self.saver = tf.train.Saver()
        could_load, checkpoint_counter = self.load(self.checkpoint_dir)

        if could_load:
            print(" [*] Load SUCCESS")
        else:
            print(" [!] Load failed...")

    def generate_sample(self, segmap_img):

        if self.segmap_ch == 1:
            segmap_img = np.expand_dims(segmap_img, axis=-1)

        label_map = convert_from_color_segmentation(self.img_class.color_value_dict, segmap_img, tensor_type=False)

        segmap_onehot = get_one_hot(label_map, len(self.img_class.color_value_dict))

        segmap_onehot = np.expand_dims(segmap_onehot, axis=0)

        fake_img = self.sess.run(self.random_test_fake_x, feed_dict={self.test_segmap_image : segmap_onehot})

        fake_rgb = fake_img[:, :, :, 0:3]
        fake_nir = fake_img[:, :, :, 3]

        # Convert to the range [0, 255]
        fake_rgb = np.rint(postprocessing(fake_rgb)).astype('uint8')[0]
        fake_nir = np.rint(postprocessing(fake_nir)).astype('uint8')[0]

        return fake_rgb, fake_nir
