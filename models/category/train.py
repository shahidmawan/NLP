from __future__ import print_function
from models.category.hyperparams import Hyperparams as hp
import tensorflow as tf
from models.category.data_load import get_batch_data, load_vocab, load_labels
from models.category.modules import *
from tqdm import tqdm

class Graph:
    def __init__(self, mode="train"):
        # Set Phase Flag
        is_training = True if mode=="train" else False

        # Load data
        if is_training: # x: text. (N, T), y: category. (N,)
            self.x, self.y, self.num_batch = get_batch_data()  # (N, T)
        else:
            self.x = tf.placeholder(tf.int32, shape=(None, hp.max_len))
            self.y = tf.placeholder(tf.int32, shape=(None,))

        # Load vocabulary
        word2idx, idx2word = load_vocab()

        # Encoder
        ## Embedding
        enc = embed(self.x,
                        vocab_size=hp.num_vocab,
                        num_units=hp.hidden_units,
                        scope="enc_embed")


        # Encoder pre-net
        prenet_out = prenet(enc,
                            num_units=[hp.hidden_units, hp.hidden_units//2],
                            dropout_rate=hp.dropout_rate,
                            is_training=is_training)  # (N, T, E/2)

        # Encoder CBHG
        ## Conv1D bank
        enc = conv1d_banks(prenet_out,
                           K=hp.encoder_num_banks,
                           is_training=is_training)  # (N, T, K * E / 2)

        ### Max pooling
        enc = tf.layers.max_pooling1d(enc, 2, 1, padding="same")  # (N, T, K * E / 2)

        ### Conv1D projections
        enc = conv1d(enc, hp.hidden_units//2, 3, scope="conv1d_1")  # (N, T, E/2)
        enc = bn(enc, is_training=is_training, activation_fn=tf.nn.relu, scope="norm1")
        enc = conv1d(enc, hp.hidden_units//2, 3, scope="conv1d_2")  # (N, T, E/2)
        enc = bn(enc, is_training=is_training, activation_fn=tf.nn.relu, scope="norm2")
        enc += prenet_out  # (N, T, E/2) # residual connections

        ### Highway Nets
        for i in range(hp.num_highwaynet_blocks):
            enc = highwaynet(enc, num_units=hp.hidden_units//2,
                             scope='highwaynet_{}'.format(i))  # (N, T, E/2)

        # Final linear projection
        _, T, E = enc.get_shape().as_list()
        enc = tf.reshape(enc, (-1, T*E))
        self.logits = tf.squeeze(tf.layers.dense(enc, len(hp.categories)))
        self.preds = tf.argmax(self.logits, -1)

        self.global_step = tf.Variable(0, name='global_step', trainable=False)
        if is_training:
            # Loss
            self.loss = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=self.logits, labels=self.y)
            self.loss = tf.reduce_mean(self.loss)

            # Training Scheme
            self.optimizer = tf.train.AdamOptimizer(learning_rate=hp.lr)
            self.train_op = self.optimizer.minimize(self.loss, global_step=self.global_step)

            # Summary
            tf.summary.scalar('loss', self.loss)
            tf.summary.merge_all()

if __name__ == '__main__':
    # Construct graph
    g = Graph()
    print("Graph loaded")

    # Load vocabulary
    word2idx, idx2word = load_vocab()
    cat2idx, idx2cat = load_labels()

    # Start a session
    sv = tf.train.Supervisor(logdir=hp.logdir)
    with sv.managed_session() as sess:
        for epoch in range(1, hp.num_epochs + 1):
            if sv.should_stop(): break
            for step in tqdm(range(g.num_batch), total=g.num_batch, ncols=70, leave=False, unit='b'):
                sess.run(g.train_op)

                # Monitor
                if step % 1000 == 0:
                    x, y, preds = sess.run([g.x, g.y, g.preds])
                    x0, y0, pred = x[0], y[0], preds[0]
                    print("input:", " ".join(idx2word[idx] for idx in x0))
                    print("label:", idx2cat[y0])
                    print("pred:", idx2cat[pred])

            # Save
            gs = sess.run(g.global_step)
            sv.saver.save(sess, hp.logdir + '/model_epoch_%02d_gs_%d' % (epoch, gs))

    print("Done")


