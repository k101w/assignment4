import torch
import torch.nn.functional as F
from diffusers import DDIMScheduler, StableDiffusionPipeline
import pdb

class SDS:
    """
    Class to implement the SDS loss function.
    """

    def __init__(
        self,
        sd_version="2.1",
        device="cpu",
        t_range=[0.02, 0.98],
        output_dir="output",
    ):
        """
        Load the Stable Diffusion model and set the parameters.

        Args:
            sd_version (str): version for stable diffusion model
            device (_type_): _description_
        """

        # Set the stable diffusion model key based on the version
        if sd_version == "2.1":
            sd_model_key = "stabilityai/stable-diffusion-2-1-base"
        else:
            raise NotImplementedError(
                f"Stable diffusion version {sd_version} not supported"
            )

        # Set parameters
        self.H = 512  # default height of Stable Diffusion
        self.W = 512  # default width of Stable Diffusion
        self.num_inference_steps = 50
        self.output_dir = output_dir
        self.device = device
        self.precision_t = torch.float32

        # Create model
        sd_pipe = StableDiffusionPipeline.from_pretrained(
            sd_model_key, torch_dtype=self.precision_t, cache_dir = "/project_data/ramanan/kewenwu/as4/assignment4/Q2"
        ).to(device)

        self.vae = sd_pipe.vae
        self.tokenizer = sd_pipe.tokenizer
        self.text_encoder = sd_pipe.text_encoder
        self.unet = sd_pipe.unet
        self.scheduler = DDIMScheduler.from_pretrained(
            sd_model_key, subfolder="scheduler", torch_dtype=self.precision_t,cache_dir = "/project_data/ramanan/kewenwu/as4/assignment4/Q2"
        )
        del sd_pipe

        self.num_train_timesteps = self.scheduler.config.num_train_timesteps
        self.min_step = int(self.num_train_timesteps * t_range[0])
        self.max_step = int(self.num_train_timesteps * t_range[1])
        self.alphas = self.scheduler.alphas_cumprod.to(
            self.device
        )  # for convenient access

        print(f"[INFO] loaded stable diffusion!")

    @torch.no_grad()
    def get_text_embeddings(self, prompt):
        """
        Get the text embeddings for the prompt.

        Args:
            prompt (list of string): text prompt to encode.
        """
        text_input = self.tokenizer(
            prompt,
            padding="max_length",
            max_length=self.tokenizer.model_max_length,
            return_tensors="pt",
        )
        text_embeddings = self.text_encoder(text_input.input_ids.to(self.device))[0]
        return text_embeddings

    def encode_imgs(self, img):
        """
        Encode the image to latent representation.

        Args:
            img (tensor): image to encode. shape (N, 3, H, W), range [0, 1]

        Returns:
            latents (tensor): latent representation. shape (1, 4, 64, 64)
        """
        # check the shape of the image should be 512x512
        assert img.shape[-2:] == (512, 512), "Image shape should be 512x512"

        img = 2 * img - 1  # [0, 1] => [-1, 1]

        posterior = self.vae.encode(img).latent_dist
        latents = posterior.sample() * self.vae.config.scaling_factor

        return latents

    def decode_latents(self, latents):
        """
        Decode the latent representation into RGB image.

        Args:
            latents (tensor): latent representation. shape (1, 4, 64, 64), range [-1, 1]

        Returns:
            imgs[0] (np.array): decoded image. shape (512, 512, 3), range [0, 255]
        """
        latents = 1 / self.vae.config.scaling_factor * latents

        imgs = self.vae.decode(latents.type(self.precision_t)).sample
        imgs = (imgs / 2 + 0.5).clamp(0, 1)  # [-1, 1] => [0, 1]
        imgs = imgs.detach().cpu().permute(0, 2, 3, 1).numpy()  # torch to numpy
        imgs = (imgs * 255).round()  # [0, 1] => [0, 255]
        return imgs[0]

    def sds_loss(
        self,
        latents,
        text_embeddings,
        text_embeddings_uncond=None,
        guidance_scale=100,
        grad_scale=1,
    ):
        """
        Compute the SDS loss.

        Args:
            latents (tensor): input latents, shape [1, 4, 64, 64]
            text_embeddings (tensor): conditional text embedding (for positive prompt), shape [1, 77, 1024]
            text_embeddings_uncond (tensor, optional): unconditional text embedding (for negative prompt), shape [1, 77, 1024]. Defaults to None.
            guidance_scale (int, optional): weight scaling for guidance. Defaults to 100.
            grad_scale (int, optional): gradient scaling. Defaults to 1.

        Returns:
            loss (tensor): SDS loss
        """

        # sample a timestep ~ U(0.02, 0.98) to avoid very high/low noise level
        t = torch.randint(
            self.min_step,
            self.max_step + 1,
            (latents.shape[0],),
            dtype=torch.long,
            device=self.device,
        )

        # predict the noise residual with unet, NO grad!
        with torch.no_grad():
            ### YOUR CODE HERE ###
            noise = torch.randn_like(latents)
            x_t = self.scheduler.add_noise(latents, noise, t)    
            noise_predict = self.unet(x_t, t, text_embeddings)["sample"]     
            if text_embeddings_uncond is not None and guidance_scale != 1:
            #     ### YOUR CODE HERE ###
                noise_predict_uncond = self.unet(x_t, t, text_embeddings_uncond)["sample"]
                noise_predict = noise_predict + guidance_scale * (noise_predict - noise_predict_uncond)

 
        # Compute SDS loss
        w = 1 - self.alphas[t]
        ### YOUR CODE HERE ###
        grad = grad_scale * w * (noise_predict - noise)
        target = (latents - grad).detach()
        loss = 0.5*F.mse_loss(latents, target)/ latents.shape[0]

        return loss


    # def sds_loss(
    #     self,
    #     latents,
    #     text_embeddings,
    #     text_embeddings_uncond=None,
    #     guidance_scale=100,
    #     grad_scale=1,
    # ):
    #     """
    #     Compute the SDS loss.

    #     Args:
    #         latents (tensor): input latents, shape [1, 4, 64, 64]
    #         text_embeddings (tensor): conditional text embedding (for positive prompt), shape [1, 77, 1024]
    #         text_embeddings_uncond (tensor, optional): unconditional text embedding (for negative prompt), shape [1, 77, 1024]. Defaults to None.
    #         guidance_scale (int, optional): weight scaling for guidance. Defaults to 100.
    #         grad_scale (int, optional): gradient scaling. Defaults to 1.

    #     Returns:
    #         loss (tensor): SDS loss
    #     """

    #     # sample a timestep ~ U(0.02, 0.98) to avoid very high/low noise level
    #     t = torch.randint(
    #         self.min_step,
    #         self.max_step + 1,
    #         (latents.shape[0],),
    #         dtype=torch.long,
    #         device=self.device,
    #     )
    #     # predict the noise residual with unet, NO grad!
    #     with torch.no_grad():
    #         ### YOUR CODE HERE ###
    #         noise  = torch.rand_like(latents)
    #         latent_noisy = self.scheduler.add_noise(latents, noise, t)
    #         noise_residual = self.unet(latent_noisy, t, text_embeddings)["sample"]

 

    #         if text_embeddings_uncond is not None and guidance_scale != 1:
    #             ### YOUR CODE HERE ###
    #             un_noise_residual = self.unet(latent_noisy, t,text_embeddings_uncond)["sample"]
    #             noise_residual = un_noise_residual + guidance_scale*(noise_residual - un_noise_residual)
 
    #     # Compute SDS loss
    #     w = 1 - self.alphas[t]
    #     grad = grad_scale * w * (noise_residual - noise)
    #     target = (latents - grad).detach()
    #     loss = 0.5*F.mse_loss(latents, target)/ latents.shape[0]

    #     return loss
